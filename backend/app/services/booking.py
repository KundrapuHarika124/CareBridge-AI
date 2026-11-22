"""Booking, cancellation and rescheduling. The only code that writes appointments.

Concurrency design
- The slot row is locked with SELECT ... FOR UPDATE before any decision is made, so two
  requests for one slot are serialized by PostgreSQL.
- A partial unique index allows only one PENDING/CONFIRMED appointment per slot, as a
  second line of defence.
- The idempotency key is checked after the lock, so a retried request returns the original
  appointment instead of a conflict.
- Success is returned only after COMMIT.
"""
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants import (
    APPT_ACTIVE,
    APPT_CANCELLED,
    APPT_COMPLETED,
    APPT_CONFIRMED,
    APPT_NO_SHOW,
    APPT_RESCHEDULED,
    SLOT_AVAILABLE,
    SLOT_BOOKED,
    SLOT_HELD,
)
from app.core import errors
from app.core.timeutil import to_utc_iso, utcnow
from app.models import (
    Affiliation,
    Appointment,
    AppointmentSlot,
    ConsultationSummary,
    Hospital,
    Patient,
    QuestionnaireResponse,
    User,
)
from app.services import directory
from app.services.common import audit, notify


def _lock_slot(db: Session, slot_id: uuid.UUID) -> AppointmentSlot | None:
    return db.execute(
        select(AppointmentSlot)
        .where(AppointmentSlot.id == slot_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _lock_hospital(db: Session, hospital_id: uuid.UUID) -> Hospital:
    hospital = db.execute(
        select(Hospital)
        .where(Hospital.id == hospital_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if hospital is None:
        db.rollback()
        raise errors.not_found("Hospital")
    return hospital


def _hospital_id_for_slot(db: Session, slot_id: uuid.UUID) -> uuid.UUID | None:
    affiliation_id = db.scalar(
        select(AppointmentSlot.affiliation_id).where(AppointmentSlot.id == slot_id)
    )
    if affiliation_id is None:
        return None
    return db.scalar(
        select(Affiliation.hospital_id).where(Affiliation.id == affiliation_id)
    )


def _require_approved_hospital(db: Session, slot: AppointmentSlot) -> None:
    hospital = _lock_hospital(db, slot.affiliation.hospital_id)
    if not hospital.is_approved:
        db.rollback()
        raise errors.not_found("Hospital")


def _lock_appointment(db: Session, appointment_id: uuid.UUID) -> Appointment | None:
    return db.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def get_appointment(db: Session, appointment_id: uuid.UUID) -> Appointment:
    appt = db.get(Appointment, appointment_id)
    if appt is None:
        raise errors.not_found("Appointment")
    return appt


def _slot_unavailable(db: Session, slot: AppointmentSlot) -> errors.AppError:
    db.rollback()
    alts = [
        {"id": str(s.id), "affiliation_id": str(s.affiliation_id), "starts_at": to_utc_iso(s.starts_at)}
        for s in directory.alternatives(db, slot)
    ]
    return errors.conflict(
        "SLOT_UNAVAILABLE", "This time is no longer available. Please choose another.", {"alternatives": alts}
    )


def _payload(appt: Appointment) -> dict:
    aff = appt.slot.affiliation
    return {
        "appointment_id": str(appt.id),
        "patient_name": appt.patient.user.full_name,
        "doctor_name": aff.doctor.user.full_name,
        "hospital_name": aff.hospital.name,
        "starts_at": to_utc_iso(appt.slot.starts_at),
    }


def _patient_busy(db: Session, patient_id: uuid.UUID, slot: AppointmentSlot, ignore: uuid.UUID | None = None) -> bool:
    stmt = (
        select(Appointment.id)
        .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.status.in_(APPT_ACTIVE),
            AppointmentSlot.starts_at == slot.starts_at,
        )
    )
    if ignore:
        stmt = stmt.where(Appointment.id != ignore)
    return db.scalar(stmt) is not None


def _existing_for_key(db: Session, key: str | None, patient_id: uuid.UUID) -> Appointment | None:
    if not key:
        return None
    existing = db.scalar(select(Appointment).where(Appointment.idempotency_key == key))
    if existing is None:
        return None
    if existing.patient_id != patient_id:
        raise errors.conflict("IDEMPOTENCY_KEY_REUSED", "This request key was already used for another booking.")
    return existing


def book(
    db: Session,
    *,
    actor: User,
    patient: Patient,
    slot_id: uuid.UUID,
    reason: str | None = None,
    idempotency_key: str | None = None,
    request_id: str | None = None,
    held_offer: bool = False,
    hospital_locked: bool = False,
    slot_locked: bool = False,
) -> Appointment:
    """Book `slot_id` for `patient`. The caller must already have authorized `actor`.

    `held_offer=True` is used only by waiting-list acceptance, where the slot is HELD
    for this patient.
    """
    if not hospital_locked:
        hospital_id = _hospital_id_for_slot(db, slot_id)
        if hospital_id is not None:
            hospital = _lock_hospital(db, hospital_id)
            if not hospital.is_approved:
                db.rollback()
                raise errors.not_found("Hospital")
    if slot_locked:
        slot = db.get(AppointmentSlot, slot_id)
    else:
        slot = _lock_slot(db, slot_id)
    if slot is None:
        raise errors.not_found("Slot")
    existing = _existing_for_key(db, idempotency_key, patient.id)
    if existing is not None:
        db.rollback()
        return get_appointment(db, existing.id)
    expected = SLOT_HELD if held_offer else SLOT_AVAILABLE
    if slot.status != expected or slot.starts_at <= utcnow():
        raise _slot_unavailable(db, slot)
    if _patient_busy(db, patient.id, slot):
        db.rollback()
        raise errors.conflict("PATIENT_TIME_CONFLICT", "The patient already has an appointment at this time.")

    appt = Appointment(
        slot_id=slot.id,
        patient_id=patient.id,
        booked_by_user_id=actor.id,
        status=APPT_CONFIRMED,
        reason_text=(reason or "").strip() or None,
        idempotency_key=idempotency_key,
    )
    slot.status = SLOT_BOOKED
    db.add(appt)
    try:
        db.flush()
        aff = slot.affiliation
        audit(
            db,
            actor_id=actor.id,
            action="APPOINTMENT_BOOKED",
            entity_type="appointment",
            entity_id=appt.id,
            hospital_id=aff.hospital_id,
            request_id=request_id,
            meta={"slot_id": str(slot.id), "patient_id": str(patient.id)},
        )
        notify(db, [patient.user_id, actor.id, aff.doctor.user_id], "APPOINTMENT_BOOKED", _payload(appt))
        db.commit()
    except IntegrityError:
        raise _slot_unavailable(db, slot)
    return appt


def cancel(
    db: Session,
    *,
    actor: User,
    appointment_id: uuid.UUID,
    reason: str | None = None,
    request_id: str | None = None,
) -> Appointment:
    """Cancel an active appointment and release its slot in the same transaction."""
    from app.services import waitlist  # local import: waitlist imports this module

    appt = db.get(Appointment, appointment_id)
    if appt is None:
        raise errors.not_found("Appointment")
    hospital_id = appt.slot.affiliation.hospital_id
    _lock_hospital(db, hospital_id)
    slot = _lock_slot(db, appt.slot_id)
    appt = _lock_appointment(db, appointment_id)
    if appt is None:
        raise errors.not_found("Appointment")
    if appt.status == APPT_CANCELLED:
        db.rollback()
        return appt  # cancelling twice is harmless
    if appt.status not in APPT_ACTIVE:
        db.rollback()
        raise errors.conflict("INVALID_STATUS", f"An appointment that is {appt.status} cannot be cancelled.")
    appt.status = APPT_CANCELLED
    appt.cancelled_at = utcnow()
    appt.cancel_reason = (reason or "").strip() or None
    db.flush()
    if slot.starts_at > utcnow():
        slot.status = SLOT_AVAILABLE
        waitlist.offer_slot(db, slot, hospital_locked=True, slot_locked=True)
    aff = slot.affiliation
    audit(
        db,
        actor_id=actor.id,
        action="APPOINTMENT_CANCELLED",
        entity_type="appointment",
        entity_id=appt.id,
        hospital_id=aff.hospital_id,
        request_id=request_id,
        meta={"by_role": actor.role},
    )
    notify(
        db,
        [appt.patient.user_id, appt.booked_by_user_id, actor.id, aff.doctor.user_id],
        "APPOINTMENT_CANCELLED",
        _payload(appt),
    )
    db.commit()
    return appt


def reschedule(
    db: Session,
    *,
    actor: User,
    appointment_id: uuid.UUID,
    new_slot_id: uuid.UUID,
    idempotency_key: str | None = None,
    request_id: str | None = None,
) -> Appointment:
    """Move an appointment to another slot atomically.

    Everything happens in one transaction: if the new slot cannot be taken, nothing
    changes and the original appointment stays exactly as it was.
    """
    from app.services import waitlist

    old = db.get(Appointment, appointment_id)
    if old is None:
        raise errors.not_found("Appointment")
    old_slot = db.get(AppointmentSlot, old.slot_id)
    new_slot = db.get(AppointmentSlot, new_slot_id)
    if old_slot is None:
        raise errors.not_found("Slot")
    if new_slot is None:
        db.rollback()
        raise errors.not_found("Slot")

    hospital_ids = {
        old_slot.affiliation.hospital_id,
        new_slot.affiliation.hospital_id,
    }
    for hospital_id in sorted(hospital_ids, key=str):
        _lock_hospital(db, hospital_id)

    locked = {sid: _lock_slot(db, sid) for sid in sorted({old.slot_id, new_slot_id}, key=str)}
    old_slot, new_slot = locked[old.slot_id], locked[new_slot_id]

    old = _lock_appointment(db, appointment_id)
    if old is None:
        raise errors.not_found("Appointment")
    existing = _existing_for_key(db, idempotency_key, old.patient_id)
    if existing is not None:
        db.rollback()
        return get_appointment(db, existing.id)
    if old.status not in APPT_ACTIVE:
        db.rollback()
        raise errors.conflict("INVALID_STATUS", f"An appointment that is {old.status} cannot be rescheduled.")
    if new_slot_id == old.slot_id:
        db.rollback()
        raise errors.bad_request("SAME_SLOT", "Choose a different time.")
    if new_slot is None:
        db.rollback()
        raise errors.not_found("Slot")
    hospital = db.get(Hospital, new_slot.affiliation.hospital_id)
    if hospital is None or not hospital.is_approved:
        db.rollback()
        raise errors.not_found("Hospital")
    if new_slot.status != SLOT_AVAILABLE or new_slot.starts_at <= utcnow():
        raise _slot_unavailable(db, new_slot)
    if _patient_busy(db, old.patient_id, new_slot, ignore=old.id):
        db.rollback()
        raise errors.conflict("PATIENT_TIME_CONFLICT", "The patient already has an appointment at this time.")

    try:
        old.status = APPT_RESCHEDULED
        db.flush()
        new = Appointment(
            slot_id=new_slot.id,
            patient_id=old.patient_id,
            booked_by_user_id=actor.id,
            status=APPT_CONFIRMED,
            reason_text=old.reason_text,
            idempotency_key=idempotency_key,
            rescheduled_from_id=old.id,
        )
        new_slot.status = SLOT_BOOKED
        db.add(new)
        db.flush()
        # Intake answers and the AI summary follow the patient to the new appointment.
        for model in (QuestionnaireResponse, ConsultationSummary):
            db.execute(update(model).where(model.appointment_id == old.id).values(appointment_id=new.id))
        if old_slot.starts_at > utcnow():
            old_slot.status = SLOT_AVAILABLE
            waitlist.offer_slot(db, old_slot, hospital_locked=True, slot_locked=True)
        aff = new_slot.affiliation
        audit(
            db,
            actor_id=actor.id,
            action="APPOINTMENT_RESCHEDULED",
            entity_type="appointment",
            entity_id=new.id,
            hospital_id=aff.hospital_id,
            request_id=request_id,
            meta={"from_appointment_id": str(old.id)},
        )
        notify(
            db,
            [new.patient.user_id, actor.id, aff.doctor.user_id, old_slot.affiliation.doctor.user_id],
            "APPOINTMENT_RESCHEDULED",
            _payload(new),
        )
        db.commit()
    except IntegrityError:
        raise _slot_unavailable(db, new_slot)
    return new


def mark_outcome(
    db: Session, *, actor: User, appointment_id: uuid.UUID, outcome: str, request_id: str | None = None
) -> Appointment:
    """Doctor or hospital admin marks a confirmed appointment COMPLETED or NO_SHOW."""
    if outcome not in (APPT_COMPLETED, APPT_NO_SHOW):
        raise errors.bad_request("INVALID_STATUS", "Outcome must be COMPLETED or NO_SHOW.")
    appt = _lock_appointment(db, appointment_id)
    if appt is None:
        raise errors.not_found("Appointment")
    if appt.status != APPT_CONFIRMED:
        db.rollback()
        raise errors.conflict("INVALID_STATUS", f"An appointment that is {appt.status} cannot be changed.")
    appt.status = outcome
    audit(
        db,
        actor_id=actor.id,
        action=f"APPOINTMENT_{outcome}",
        entity_type="appointment",
        entity_id=appt.id,
        hospital_id=appt.slot.affiliation.hospital_id,
        request_id=request_id,
    )
    db.commit()
    return appt
