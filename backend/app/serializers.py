"""Turn ORM rows into response dicts. Each function decides what a caller may see."""
from app.core.timeutil import to_utc_iso
from app.models import (
    Affiliation,
    Appointment,
    AppointmentSlot,
    CareRelationship,
    Hospital,
    Notification,
    Specialty,
    User,
)


def user_out(user: User, *, patient=None, doctor=None, hospital_ids=None) -> dict:
    out = {
        "id": user.id,
        "full_name": user.full_name,
        "phone": user.phone,
        "email": user.email,
        "role": user.role,
        "preferred_language": user.preferred_language,
        "patient_id": patient.id if patient else None,
        "doctor_id": doctor.id if doctor else None,
        "hospital_ids": hospital_ids or [],
    }
    if patient:
        out["patient_profile"] = {
            "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
            "sex": patient.sex,
            "accessibility_notes": patient.accessibility_notes,
        }
    return out


def specialty_out(s: Specialty) -> dict:
    return {"id": s.id, "code": s.code, "name_en": s.name_en, "name_te": s.name_te}


def hospital_out(h: Hospital) -> dict:
    return {
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
    }


def slot_out(slot: AppointmentSlot) -> dict:
    return {
        "id": slot.id,
        "affiliation_id": slot.affiliation_id,
        "starts_at": to_utc_iso(slot.starts_at),
        "ends_at": to_utc_iso(slot.ends_at),
        "status": slot.status,
    }


def affiliation_out(aff: Affiliation, next_slots: list[AppointmentSlot] | None = None) -> dict:
    return {
        "affiliation_id": aff.id,
        "doctor_id": aff.doctor_id,
        "doctor_name": aff.doctor.user.full_name,
        "qualifications": aff.doctor.qualifications,
        "years_experience": aff.doctor.years_experience,
        "verification_status": aff.doctor.verification_status,
        "specialty": specialty_out(aff.specialty),
        "hospital": hospital_out(aff.hospital),
        "department": {"id": aff.department.id, "name": aff.department.name},
        "consultation_fee": float(aff.consultation_fee) if aff.consultation_fee is not None else None,
        "is_active": aff.is_active,
        "next_slots": [slot_out(s) for s in (next_slots or [])],
    }


def appointment_out(appt: Appointment, *, include_reason: bool = True, extras: dict | None = None) -> dict:
    slot = appt.slot
    aff = slot.affiliation
    out = {
        "id": appt.id,
        "status": appt.status,
        "slot_id": slot.id,
        "affiliation_id": aff.id,
        "starts_at": to_utc_iso(slot.starts_at),
        "ends_at": to_utc_iso(slot.ends_at),
        "patient": {"id": appt.patient_id, "full_name": appt.patient.user.full_name},
        "doctor_name": aff.doctor.user.full_name,
        "specialty": specialty_out(aff.specialty),
        "hospital": hospital_out(aff.hospital),
        "consultation_fee": float(aff.consultation_fee) if aff.consultation_fee is not None else None,
        "booked_by_user_id": appt.booked_by_user_id,
        "rescheduled_from_id": appt.rescheduled_from_id,
        "cancelled_at": to_utc_iso(appt.cancelled_at),
        "cancel_reason": appt.cancel_reason,
        "created_at": to_utc_iso(appt.created_at),
    }
    if include_reason:
        out["reason_text"] = appt.reason_text
    if extras:
        out.update(extras)
    return out


def relationship_out(rel: CareRelationship, permissions: list[str]) -> dict:
    return {
        "id": rel.id,
        "status": rel.status,
        "caregiver": {"id": rel.caregiver_user_id, "full_name": rel.caregiver.full_name},
        "patient": {"id": rel.patient_id, "full_name": rel.patient.user.full_name},
        "requested_permissions": rel.requested_permissions,
        "permissions": sorted(permissions),
        "requested_at": to_utc_iso(rel.requested_at),
        "decided_at": to_utc_iso(rel.decided_at),
        "revoked_at": to_utc_iso(rel.revoked_at),
    }


def notification_out(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "payload": n.payload,
        "status": n.status,
        "read_at": to_utc_iso(n.read_at),
        "created_at": to_utc_iso(n.created_at),
    }
