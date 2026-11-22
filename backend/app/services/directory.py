"""Hospitals, doctors, schedules, slot generation and availability search."""
import math
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import SLOT_AVAILABLE
from app.core.timeutil import ist_day_bounds_utc, ist_to_utc, time_of_day, today_ist, utcnow
from app.models import Affiliation, AppointmentSlot, Doctor, DoctorSchedule, Hospital, User


def localities(db: Session) -> list[str]:
    return list(db.scalars(select(Hospital.locality).distinct().order_by(Hospital.locality)))


def available_slots(
    db: Session,
    affiliation_id: uuid.UUID,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 200,
) -> list[AppointmentSlot]:
    """Future AVAILABLE slots only. Nothing else is ever offered for booking."""
    now = utcnow()
    lower = max(start, now) if start else now
    stmt = select(AppointmentSlot).where(
        AppointmentSlot.affiliation_id == affiliation_id,
        AppointmentSlot.status == SLOT_AVAILABLE,
        AppointmentSlot.starts_at > lower,
    )
    if end:
        stmt = stmt.where(AppointmentSlot.starts_at < end)
    return list(db.scalars(stmt.order_by(AppointmentSlot.starts_at).limit(limit)))


def search_affiliations(
    db: Session,
    *,
    specialty_id: uuid.UUID | None = None,
    hospital_id: uuid.UUID | None = None,
    locality: str | None = None,
    q: str | None = None,
    on_date: date | None = None,
    include_inactive: bool = False,
) -> list[tuple[Affiliation, list[AppointmentSlot]]]:
    stmt = (
        select(Affiliation)
        .join(Hospital, Hospital.id == Affiliation.hospital_id)
        .join(Doctor, Doctor.id == Affiliation.doctor_id)
        .join(User, User.id == Doctor.user_id)
        .where(Hospital.is_approved.is_(True))
    )
    if not include_inactive:
        stmt = stmt.where(Affiliation.is_active.is_(True), User.is_active.is_(True))
    if specialty_id:
        stmt = stmt.where(Affiliation.specialty_id == specialty_id)
    if hospital_id:
        stmt = stmt.where(Affiliation.hospital_id == hospital_id)
    if locality:
        stmt = stmt.where(func.lower(Hospital.locality) == locality.strip().lower())
    if q:
        stmt = stmt.where(User.full_name.ilike(f"%{q.strip()}%"))
    results = []
    for aff in db.scalars(stmt.order_by(User.full_name)).all():
        if on_date:
            start, end = ist_day_bounds_utc(on_date)
            slots = available_slots(db, aff.id, start=start, end=end, limit=3)
        else:
            slots = available_slots(db, aff.id, limit=3)
        results.append((aff, slots))
    return results


def find_slot_options(
    db: Session,
    *,
    specialty_id: uuid.UUID,
    locality: str | None = None,
    on_date: date | None = None,
    tod: str | None = None,
    limit: int = 3,
) -> list[AppointmentSlot]:
    """Earliest matching slots, at most one per doctor, for the assistant to offer."""
    stmt = (
        select(AppointmentSlot)
        .join(Affiliation, Affiliation.id == AppointmentSlot.affiliation_id)
        .join(Hospital, Hospital.id == Affiliation.hospital_id)
        .where(
            Hospital.is_approved.is_(True),
            Affiliation.specialty_id == specialty_id,
            Affiliation.is_active.is_(True),
            AppointmentSlot.status == SLOT_AVAILABLE,
            AppointmentSlot.starts_at > utcnow(),
        )
    )
    if locality:
        stmt = stmt.where(func.lower(Hospital.locality) == locality.strip().lower())
    if on_date:
        start, end = ist_day_bounds_utc(on_date)
        stmt = stmt.where(AppointmentSlot.starts_at >= start, AppointmentSlot.starts_at < end)
    picked: list[AppointmentSlot] = []
    seen: set[uuid.UUID] = set()
    for slot in db.scalars(stmt.order_by(AppointmentSlot.starts_at).limit(300)):
        if tod and time_of_day(slot.starts_at) != tod:
            continue
        if slot.affiliation_id in seen:
            continue
        seen.add(slot.affiliation_id)
        picked.append(slot)
        if len(picked) >= limit:
            break
    return picked


def alternatives(db: Session, slot: AppointmentSlot, limit: int = 3) -> list[AppointmentSlot]:
    """Other open slots to suggest when `slot` could not be booked."""
    same_doctor = [s for s in available_slots(db, slot.affiliation_id, limit=limit + 1) if s.id != slot.id]
    if same_doctor:
        return same_doctor[:limit]
    aff = db.get(Affiliation, slot.affiliation_id)
    others = find_slot_options(db, specialty_id=aff.specialty_id, limit=limit + 1)
    return [s for s in others if s.id != slot.id][:limit]


def haversine_distance(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Calculate the great circle distance between two points on Earth in kilometers."""
    R = 6371.0  # Earth radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def nearby_hospitals(
    db: Session,
    patient_lat: float,
    patient_lon: float,
    max_distance_km: float = 50.0,
    limit: int = 100,
    include_unapproved: bool = False,
    approved_only: bool = True,
) -> list[dict]:
    """
    Find hospitals near the given coordinates.

    Args:
        db: Database session
        patient_lat: Patient's latitude
        patient_lon: Patient's longitude
        max_distance_km: Maximum distance in km
        limit: Maximum number of results
        include_unapproved: If True, include unapproved hospitals
        approved_only: If True, only return approved hospitals (default: True)

    Returns:
        List of hospital dicts with latitude, longitude, and distance_km
    """
    hospitals = db.scalars(
        select(Hospital)
        .where(Hospital.latitude.is_not(None), Hospital.longitude.is_not(None))
    ).all()

    results = []
    for h in hospitals:
        if approved_only and not h.is_approved:
            continue
        dist = haversine_distance(patient_lat, patient_lon, h.latitude, h.longitude)
        if dist <= max_distance_km:
            results.append({
                "id": str(h.id),
                "name": h.name,
                "locality": h.locality,
                "city": h.city,
                "address": h.address,
                "phone": h.phone,
                "is_simulated": h.is_simulated,
                "latitude": h.latitude,
                "longitude": h.longitude,
                "is_approved": h.is_approved,
                "distance_km": round(dist, 2),
            })

    return sorted(results, key=lambda x: x["distance_km"])[:limit]


def search_doctors_nearby(
    db: Session,
    patient_lat: float,
    patient_lon: float,
    specialty_id: uuid.UUID | None = None,
    locality: str | None = None,
    max_distance_km: float = 50.0,
    limit: int = 20,
) -> list[dict]:
    """
    Find doctors at nearby hospitals, optionally filtered by specialty.

    Returns doctors belonging to approved hospitals within the given distance,
    with information about the hospital's location.
    """
    # First get nearby hospitals
    nearby = nearby_hospitals(db, patient_lat, patient_lon, max_distance_km, limit * 5, approved_only=True)
    hospital_ids = [h["id"] for h in nearby]

    if not hospital_ids:
        return []

    # Build lookup for distances
    distance_map = {h["id"]: h["distance_km"] for h in nearby}

    # Search affiliations at these hospitals
    stmt = (
        select(Affiliation)
        .join(Hospital, Hospital.id == Affiliation.hospital_id)
        .join(Doctor, Doctor.id == Affiliation.doctor_id)
        .join(User, User.id == Doctor.user_id)
        .where(
            Affiliation.hospital_id.in_(hospital_ids),
            Affiliation.is_active.is_(True),
            User.is_active.is_(True),
            Hospital.is_approved.is_(True),
        )
    )
    if specialty_id:
        stmt = stmt.where(Affiliation.specialty_id == specialty_id)
    if locality:
        stmt = stmt.where(func.lower(Hospital.locality) == locality.strip().lower())

    results = []
    for aff in db.scalars(stmt.order_by(User.full_name).limit(limit * 3)).all():
        h_id = str(aff.hospital.id)
        if h_id in distance_map:
            slots = available_slots(db, aff.id, limit=2)
            results.append({
                "affiliation_id": str(aff.id),
                "doctor_id": str(aff.doctor.id),
                "doctor_name": aff.doctor.user.full_name,
                "qualifications": aff.doctor.qualifications,
                "years_experience": aff.doctor.years_experience,
                "verification_status": aff.doctor.verification_status,
                "specialty": {"id": str(aff.specialty.id), "code": aff.specialty.code,
                             "name_en": aff.specialty.name_en, "name_te": aff.specialty.name_te},
                "hospital": {
                    "id": h_id,
                    "name": aff.hospital.name,
                    "locality": aff.hospital.locality,
                    "city": aff.hospital.city,
                    "address": aff.hospital.address,
                    "phone": aff.hospital.phone,
                    "is_simulated": aff.hospital.is_simulated,
                    "latitude": aff.hospital.latitude,
                    "longitude": aff.hospital.longitude,
                    "is_approved": aff.hospital.is_approved,
                    "distance_km": distance_map[h_id],
                },
                "department": {"id": str(aff.department.id), "name": aff.department.name},
                "consultation_fee": float(aff.consultation_fee) if aff.consultation_fee else None,
                "is_active": aff.is_active,
                "next_slots": [{"id": str(s.id), "starts_at": s.starts_at.isoformat(),
                               "ends_at": s.ends_at.isoformat(), "status": s.status} for s in slots],
            })

    return sorted(results, key=lambda x: x["hospital"]["distance_km"])[:limit]


def generate_slots(db: Session, aff: Affiliation, days: int = 14) -> int:
    """Create AVAILABLE slots from the weekly schedules for the next `days` days (IST).

    Idempotent: times that already have a slot for this doctor are skipped, which also
    prevents one doctor being given the same start time at two hospitals. Does not commit.
    """
    schedules = list(db.scalars(select(DoctorSchedule).where(DoctorSchedule.affiliation_id == aff.id)))
    if not schedules:
        return 0
    first_day = today_ist()
    range_start, _ = ist_day_bounds_utc(first_day)
    _, range_end = ist_day_bounds_utc(first_day + timedelta(days=days - 1))
    taken = set(
        db.scalars(
            select(AppointmentSlot.starts_at).where(
                AppointmentSlot.doctor_id == aff.doctor_id,
                AppointmentSlot.starts_at >= range_start,
                AppointmentSlot.starts_at < range_end,
            )
        )
    )
    now = utcnow()
    created = 0
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        for sched in schedules:
            if sched.weekday != day.weekday():
                continue
            cursor = ist_to_utc(day, sched.start_time)
            end = ist_to_utc(day, sched.end_time)
            step = timedelta(minutes=sched.slot_minutes)
            while cursor + step <= end:
                if cursor > now and cursor not in taken:
                    db.add(
                        AppointmentSlot(
                            affiliation_id=aff.id,
                            doctor_id=aff.doctor_id,
                            starts_at=cursor,
                            ends_at=cursor + step,
                            status=SLOT_AVAILABLE,
                        )
                    )
                    taken.add(cursor)
                    created += 1
                cursor += step
    return created
