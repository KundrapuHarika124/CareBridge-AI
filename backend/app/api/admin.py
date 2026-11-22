"""Hospital administration. Every route is scoped to a hospital the caller belongs to.

Hospital admins manage logistics only. They never receive reasons for visits, intake
answers, summaries, notes or follow-up instructions.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    APPT_ACTIVE,
    APPT_CANCELLED,
    APPT_CONFIRMED,
    ROLE_DOCTOR,
    ROLE_HOSPITAL_ADMIN,
    SLOT_AVAILABLE,
    SLOT_BLOCKED,
    WAIT_ACTIVE,
    WAIT_OFFERED,
)
from app.core import errors
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.errors import ok, request_id_of
from app.core.security import hash_password
from app.core.timeutil import ist_day_bounds_utc, today_ist, utcnow
from app.models import (
    Affiliation,
    Appointment,
    AppointmentSlot,
    Department,
    Doctor,
    DoctorSchedule,
    Hospital,
    Specialty,
    User,
    WaitingListEntry,
)
from app.schemas import (
    AffiliationPatchIn,
    CancelIn,
    DepartmentIn,
    DoctorCreateIn,
    GenerateSlotsIn,
    ScheduleIn,
    normalize_identifier,
)
from app.serializers import affiliation_out, appointment_out, hospital_out, slot_out
from app.services import access, booking, directory, waitlist
from app.services.common import audit

router = APIRouter(prefix="/admin/hospitals/{hospital_id}")
_admin = require_roles(ROLE_HOSPITAL_ADMIN)


def _affiliation(db: Session, hospital_id: uuid.UUID, affiliation_id: uuid.UUID) -> Affiliation:
    aff = db.get(Affiliation, affiliation_id)
    if aff is None or aff.hospital_id != hospital_id:
        raise errors.not_found("Doctor")
    return aff


def _schedule_out(s: DoctorSchedule) -> dict:
    return {
        "id": s.id,
        "weekday": s.weekday,
        "start_time": s.start_time.strftime("%H:%M"),
        "end_time": s.end_time.strftime("%H:%M"),
        "slot_minutes": s.slot_minutes,
    }


@router.get("")
def hospital(hospital_id: uuid.UUID, request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)):
    access.require_hospital_admin(db, user, hospital_id)
    return ok(request, hospital_out(db.get(Hospital, hospital_id)))


@router.get("/overview")
def overview(hospital_id: uuid.UUID, request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)):
    access.require_hospital_admin(db, user, hospital_id)
    now = utcnow()
    day_start, day_end = ist_day_bounds_utc(today_ist())
    slots_here = (
        select(AppointmentSlot.id)
        .join(Affiliation, Affiliation.id == AppointmentSlot.affiliation_id)
        .where(Affiliation.hospital_id == hospital_id)
    )

    def count_appointments(*conditions) -> int:
        stmt = (
            select(func.count(Appointment.id))
            .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
            .join(Affiliation, Affiliation.id == AppointmentSlot.affiliation_id)
            .where(Affiliation.hospital_id == hospital_id, *conditions)
        )
        return db.scalar(stmt) or 0

    data = {
        "active_doctors": db.scalar(
            select(func.count(Affiliation.id)).where(Affiliation.hospital_id == hospital_id, Affiliation.is_active.is_(True))
        ) or 0,
        "appointments_today": count_appointments(
            Appointment.status.in_(APPT_ACTIVE), AppointmentSlot.starts_at >= day_start, AppointmentSlot.starts_at < day_end
        ),
        "upcoming_confirmed": count_appointments(Appointment.status == APPT_CONFIRMED, AppointmentSlot.starts_at > now),
        "cancelled_last_7_days": count_appointments(
            Appointment.status == APPT_CANCELLED, Appointment.cancelled_at >= now - timedelta(days=7)
        ),
        "open_slots_next_7_days": db.scalar(
            select(func.count(AppointmentSlot.id)).where(
                AppointmentSlot.id.in_(slots_here),
                AppointmentSlot.status == SLOT_AVAILABLE,
                AppointmentSlot.starts_at > now,
                AppointmentSlot.starts_at <= now + timedelta(days=7),
            )
        ) or 0,
        "waiting_list": db.scalar(
            select(func.count(WaitingListEntry.id))
            .join(Affiliation, Affiliation.id == WaitingListEntry.affiliation_id)
            .where(Affiliation.hospital_id == hospital_id, WaitingListEntry.status.in_((WAIT_ACTIVE, WAIT_OFFERED)))
        ) or 0,
    }
    return ok(request, data)


@router.get("/departments")
def departments(hospital_id: uuid.UUID, request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)):
    access.require_hospital_admin(db, user, hospital_id)
    rows = db.scalars(select(Department).where(Department.hospital_id == hospital_id).order_by(Department.name)).all()
    return ok(request, [{"id": d.id, "name": d.name} for d in rows])


@router.post("/departments", status_code=201)
def create_department(
    hospital_id: uuid.UUID, body: DepartmentIn, request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)
):
    access.require_hospital_admin(db, user, hospital_id)
    name = body.name.strip()
    exists = db.scalar(
        select(Department).where(Department.hospital_id == hospital_id, func.lower(Department.name) == name.lower())
    )
    if exists:
        raise errors.conflict("DEPARTMENT_EXISTS", "A department with this name already exists.")
    dept = Department(hospital_id=hospital_id, name=name)
    db.add(dept)
    db.flush()
    audit(db, actor_id=user.id, action="DEPARTMENT_CREATED", entity_type="department", entity_id=dept.id,
          hospital_id=hospital_id, request_id=request_id_of(request))
    db.commit()
    return ok(request, {"id": dept.id, "name": dept.name})


@router.get("/doctors")
def doctors(hospital_id: uuid.UUID, request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)):
    access.require_hospital_admin(db, user, hospital_id)
    results = directory.search_affiliations(db, hospital_id=hospital_id, include_inactive=True)
    return ok(request, [affiliation_out(aff, slots) for aff, slots in results])


@router.post("/doctors", status_code=201)
def add_doctor(
    hospital_id: uuid.UUID, body: DoctorCreateIn, request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)
):
    """Create a doctor account and attach it to this hospital, or attach an existing doctor."""
    access.require_hospital_admin(db, user, hospital_id)
    dept = db.get(Department, body.department_id)
    if dept is None or dept.hospital_id != hospital_id:
        raise errors.not_found("Department")
    if db.get(Specialty, body.specialty_id) is None:
        raise errors.not_found("Specialty")
    kind, value = normalize_identifier(body.identifier)
    column = User.phone if kind == "phone" else User.email
    account = db.scalar(select(User).where(column == value))
    if account is not None and account.role != ROLE_DOCTOR:
        raise errors.conflict("IDENTIFIER_TAKEN", "This phone number or email belongs to a non-doctor account.")
    if account is None:
        if not body.password:
            raise errors.bad_request("PASSWORD_REQUIRED", "Set an initial password for the new doctor account.")
        account = User(
            full_name=body.full_name.strip(),
            phone=value if kind == "phone" else None,
            email=value if kind == "email" else None,
            password_hash=hash_password(body.password),
            role=ROLE_DOCTOR,
            preferred_language="en",
        )
        db.add(account)
        db.flush()
        doctor = Doctor(user_id=account.id, qualifications=body.qualifications.strip(),
                        years_experience=body.years_experience)
        db.add(doctor)
        db.flush()
    else:
        doctor = db.scalar(select(Doctor).where(Doctor.user_id == account.id))
    duplicate = db.scalar(
        select(Affiliation).where(
            Affiliation.doctor_id == doctor.id, Affiliation.hospital_id == hospital_id, Affiliation.department_id == dept.id
        )
    )
    if duplicate:
        raise errors.conflict("AFFILIATION_EXISTS", "This doctor is already in this department.")
    aff = Affiliation(
        doctor_id=doctor.id,
        hospital_id=hospital_id,
        department_id=dept.id,
        specialty_id=body.specialty_id,
        consultation_fee=Decimal(str(body.consultation_fee)) if body.consultation_fee is not None else None,
    )
    db.add(aff)
    db.flush()
    audit(db, actor_id=user.id, action="DOCTOR_ADDED", entity_type="affiliation", entity_id=aff.id,
          hospital_id=hospital_id, request_id=request_id_of(request))
    db.commit()
    return ok(request, affiliation_out(aff))


@router.patch("/affiliations/{affiliation_id}")
def update_affiliation(
    hospital_id: uuid.UUID, affiliation_id: uuid.UUID, body: AffiliationPatchIn, request: Request,
    user: User = Depends(_admin), db: Session = Depends(get_db),
):
    access.require_hospital_admin(db, user, hospital_id)
    aff = _affiliation(db, hospital_id, affiliation_id)
    if "consultation_fee" in body.model_fields_set:
        aff.consultation_fee = Decimal(str(body.consultation_fee)) if body.consultation_fee is not None else None
    if body.is_active is not None:
        aff.is_active = body.is_active
    audit(db, actor_id=user.id, action="AFFILIATION_UPDATED", entity_type="affiliation", entity_id=aff.id,
          hospital_id=hospital_id, request_id=request_id_of(request))
    db.commit()
    return ok(request, affiliation_out(aff))


@router.get("/affiliations/{affiliation_id}/schedules")
def schedules(
    hospital_id: uuid.UUID, affiliation_id: uuid.UUID, request: Request,
    user: User = Depends(_admin), db: Session = Depends(get_db),
):
    access.require_hospital_admin(db, user, hospital_id)
    aff = _affiliation(db, hospital_id, affiliation_id)
    rows = db.scalars(
        select(DoctorSchedule).where(DoctorSchedule.affiliation_id == aff.id).order_by(DoctorSchedule.weekday, DoctorSchedule.start_time)
    ).all()
    return ok(request, [_schedule_out(s) for s in rows])


@router.post("/affiliations/{affiliation_id}/schedules", status_code=201)
def add_schedule(
    hospital_id: uuid.UUID, affiliation_id: uuid.UUID, body: ScheduleIn, request: Request,
    user: User = Depends(_admin), db: Session = Depends(get_db),
):
    access.require_hospital_admin(db, user, hospital_id)
    aff = _affiliation(db, hospital_id, affiliation_id)
    if body.end_time <= body.start_time:
        raise errors.bad_request("INVALID_TIMES", "End time must be after start time.")
    overlapping = db.scalar(
        select(DoctorSchedule).where(
            DoctorSchedule.affiliation_id == aff.id,
            DoctorSchedule.weekday == body.weekday,
            DoctorSchedule.start_time < body.end_time,
            DoctorSchedule.end_time > body.start_time,
        )
    )
    if overlapping:
        raise errors.conflict("SCHEDULE_OVERLAP", "This overlaps an existing schedule for that day.")
    sched = DoctorSchedule(
        affiliation_id=aff.id, weekday=body.weekday, start_time=body.start_time, end_time=body.end_time,
        slot_minutes=body.slot_minutes,
    )
    db.add(sched)
    db.flush()
    audit(db, actor_id=user.id, action="SCHEDULE_ADDED", entity_type="schedule", entity_id=sched.id,
          hospital_id=hospital_id, request_id=request_id_of(request))
    db.commit()
    return ok(request, _schedule_out(sched))


@router.delete("/schedules/{schedule_id}")
def delete_schedule(
    hospital_id: uuid.UUID, schedule_id: uuid.UUID, request: Request,
    user: User = Depends(_admin), db: Session = Depends(get_db),
):
    """Remove a weekly pattern. Slots already generated from it are left untouched."""
    access.require_hospital_admin(db, user, hospital_id)
    sched = db.get(DoctorSchedule, schedule_id)
    if sched is None:
        raise errors.not_found("Schedule")
    _affiliation(db, hospital_id, sched.affiliation_id)
    db.delete(sched)
    audit(db, actor_id=user.id, action="SCHEDULE_DELETED", entity_type="schedule", entity_id=schedule_id,
          hospital_id=hospital_id, request_id=request_id_of(request))
    db.commit()
    return ok(request, {"deleted": True})


@router.post("/affiliations/{affiliation_id}/slots/generate")
def generate_slots(
    hospital_id: uuid.UUID, affiliation_id: uuid.UUID, body: GenerateSlotsIn, request: Request,
    user: User = Depends(_admin), db: Session = Depends(get_db),
):
    access.require_hospital_admin(db, user, hospital_id)
    aff = _affiliation(db, hospital_id, affiliation_id)
    created = directory.generate_slots(db, aff, body.days)
    audit(db, actor_id=user.id, action="SLOTS_GENERATED", entity_type="affiliation", entity_id=aff.id,
          hospital_id=hospital_id, request_id=request_id_of(request), meta={"created": created, "days": body.days})
    db.commit()
    return ok(request, {"created": created})


@router.get("/affiliations/{affiliation_id}/slots")
def list_slots(
    hospital_id: uuid.UUID, affiliation_id: uuid.UUID, request: Request, on_date: date | None = None,
    user: User = Depends(_admin), db: Session = Depends(get_db),
):
    access.require_hospital_admin(db, user, hospital_id)
    aff = _affiliation(db, hospital_id, affiliation_id)
    start, end = ist_day_bounds_utc(on_date or today_ist())
    rows = db.scalars(
        select(AppointmentSlot)
        .where(AppointmentSlot.affiliation_id == aff.id, AppointmentSlot.starts_at >= start, AppointmentSlot.starts_at < end)
        .order_by(AppointmentSlot.starts_at)
    ).all()
    return ok(request, [slot_out(s) for s in rows])


def _change_slot(db: Session, user: User, hospital_id: uuid.UUID, slot_id: uuid.UUID, block: bool, request: Request) -> dict:
    access.require_hospital_admin(db, user, hospital_id)
    hospital = db.execute(
        select(Hospital)
        .where(Hospital.id == hospital_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if hospital is None or not hospital.is_approved:
        raise errors.not_found("Hospital")
    slot = db.execute(
        select(AppointmentSlot).where(AppointmentSlot.id == slot_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if slot is None:
        raise errors.not_found("Slot")
    _affiliation(db, hospital_id, slot.affiliation_id)
    expected, target = (SLOT_AVAILABLE, SLOT_BLOCKED) if block else (SLOT_BLOCKED, SLOT_AVAILABLE)
    if slot.status != expected:
        db.rollback()
        raise errors.conflict("INVALID_STATUS", f"Only a slot that is {expected} can be changed this way.")
    slot.status = target
    if not block:
        waitlist.offer_slot(db, slot, hospital_locked=True, slot_locked=True)
    audit(db, actor_id=user.id, action="SLOT_BLOCKED" if block else "SLOT_UNBLOCKED", entity_type="slot",
          entity_id=slot.id, hospital_id=hospital_id, request_id=request_id_of(request))
    db.commit()
    return ok(request, slot_out(slot))


@router.post("/slots/{slot_id}/block")
def block_slot(hospital_id: uuid.UUID, slot_id: uuid.UUID, request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)):
    return _change_slot(db, user, hospital_id, slot_id, True, request)


@router.post("/slots/{slot_id}/unblock")
def unblock_slot(hospital_id: uuid.UUID, slot_id: uuid.UUID, request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)):
    return _change_slot(db, user, hospital_id, slot_id, False, request)


@router.get("/appointments")
def appointments(
    hospital_id: uuid.UUID, request: Request, on_date: date | None = None, status: str | None = None,
    user: User = Depends(_admin), db: Session = Depends(get_db),
):
    access.require_hospital_admin(db, user, hospital_id)
    stmt = (
        select(Appointment)
        .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .join(Affiliation, Affiliation.id == AppointmentSlot.affiliation_id)
        .where(Affiliation.hospital_id == hospital_id)
    )
    if on_date:
        start, end = ist_day_bounds_utc(on_date)
        stmt = stmt.where(AppointmentSlot.starts_at >= start, AppointmentSlot.starts_at < end)
    if status:
        stmt = stmt.where(Appointment.status == status.upper())
    rows = db.scalars(stmt.order_by(AppointmentSlot.starts_at).limit(300)).all()
    data = [appointment_out(a, include_reason=False, extras={"viewer": "ADMIN"}) for a in rows]
    return ok(request, data, total=len(data))


@router.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(
    hospital_id: uuid.UUID, appointment_id: uuid.UUID, body: CancelIn, request: Request,
    user: User = Depends(_admin), db: Session = Depends(get_db),
):
    access.require_hospital_admin(db, user, hospital_id)
    appt = booking.get_appointment(db, appointment_id)
    if appt.slot.affiliation.hospital_id != hospital_id:
        raise errors.not_found("Appointment")
    if not (body.reason or "").strip():
        raise errors.bad_request("REASON_REQUIRED", "Give a reason when the hospital cancels an appointment.")
    appt = booking.cancel(db, actor=user, appointment_id=appt.id, reason=body.reason, request_id=request_id_of(request))
    return ok(request, appointment_out(appt, include_reason=False, extras={"viewer": "ADMIN"}))
