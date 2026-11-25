"""Appointments, doctor workflow, pre-consultation information and the waiting list."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import (
    APPT_ACTIVE,
    APPT_COMPLETED,
    APPT_NO_SHOW,
    OFFER_OPEN,
    PERM_BOOK_APPOINTMENTS,
    PERM_CANCEL_APPOINTMENTS,
    PERM_RESCHEDULE_APPOINTMENTS,
    PERM_VIEW_APPOINTMENTS,
    PERM_VIEW_PRECONSULTATION_INFORMATION,
    ROLE_CAREGIVER,
    ROLE_DOCTOR,
    ROLE_PATIENT,
    WAIT_ACTIVE,
    WAIT_OFFERED,
)
from app.core import errors
from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.core.errors import ok, request_id_of
from app.core.timeutil import ist_day_bounds_utc, to_utc_iso, today_ist, utcnow
from app.models import (
    Appointment,
    AppointmentSlot,
    ConsultationSummary,
    FollowUpInstruction,
    QuestionnaireResponse,
    User,
    WaitingListEntry,
    WaitingListOffer,
)
from app.schemas import (
    BookIn,
    CancelIn,
    FollowUpIn,
    IntakeIn,
    NoteIn,
    RescheduleIn,
    SummaryPatchIn,
    WaitlistIn,
)
from app.serializers import affiliation_out, appointment_out, slot_out
from app.services import access, booking, clinical, waitlist
from app.services.common import audit

router = APIRouter()


def _clean_key(key: str | None) -> str | None:
    if key is None:
        return None
    key = key.strip()
    if not key or len(key) > 100:
        raise errors.bad_request("INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 1 to 100 characters.")
    return key


def _view(db: Session, user: User, appt: Appointment, viewer: str) -> dict:
    """Appointment as this viewer may see it. Admins and view-only caregivers get no reason text."""
    include_reason = viewer in ("SELF", "DOCTOR")
    permissions: list[str] = []
    if viewer == "CAREGIVER":
        permissions = sorted(access.caregiver_permissions(db, user.id, appt.patient_id))
        include_reason = PERM_VIEW_PRECONSULTATION_INFORMATION in permissions
    extras = {"viewer": viewer, "caregiver_permissions": permissions}
    if viewer != "ADMIN":
        summary = db.scalar(select(ConsultationSummary).where(ConsultationSummary.appointment_id == appt.id))
        extras["has_intake"] = (
            db.scalar(select(QuestionnaireResponse.id).where(QuestionnaireResponse.appointment_id == appt.id)) is not None
        )
        extras["has_summary"] = summary is not None and (viewer == "SELF" or summary.patient_reviewed_at is not None)
        extras["has_follow_up"] = (
            db.scalar(select(FollowUpInstruction.id).where(FollowUpInstruction.appointment_id == appt.id)) is not None
        )
    return appointment_out(appt, include_reason=include_reason, extras=extras)


# ------------------------------------------------------------------ booking

@router.post("/appointments", status_code=201)
def book(
    body: BookIn,
    request: Request,
    idempotency_key: str | None = Header(default=None),
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)),
    db: Session = Depends(get_db),
):
    patient = access.require_patient_access(db, user, body.patient_id, PERM_BOOK_APPOINTMENTS)
    appt = booking.book(
        db,
        actor=user,
        patient=patient,
        slot_id=body.slot_id,
        reason=body.reason_text,
        idempotency_key=_clean_key(idempotency_key),
        request_id=request_id_of(request),
    )
    return ok(request, _view(db, user, appt, "SELF" if user.role == ROLE_PATIENT else "CAREGIVER"))


@router.get("/appointments")
def list_appointments(
    request: Request,
    patient_id: uuid.UUID | None = None,
    scope: str = "all",
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)),
    db: Session = Depends(get_db),
):
    if user.role == ROLE_PATIENT:
        patient = access.patient_of(db, user)
        if patient is None or (patient_id is not None and patient_id != patient.id):
            raise errors.not_found("Patient")
        viewer = "SELF"
    else:
        if patient_id is None:
            raise errors.bad_request("PATIENT_REQUIRED", "Choose a patient first.")
        patient = access.require_patient_access(db, user, patient_id, PERM_VIEW_APPOINTMENTS)
        viewer = "CAREGIVER"
    stmt = (
        select(Appointment)
        .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .where(Appointment.patient_id == patient.id)
    )
    now = utcnow()
    if scope == "upcoming":
        stmt = stmt.where(Appointment.status.in_(APPT_ACTIVE), AppointmentSlot.starts_at > now).order_by(
            AppointmentSlot.starts_at
        )
    elif scope == "past":
        stmt = stmt.where(
            (AppointmentSlot.starts_at <= now) | Appointment.status.not_in(APPT_ACTIVE)
        ).order_by(AppointmentSlot.starts_at.desc())
    else:
        stmt = stmt.order_by(AppointmentSlot.starts_at.desc())
    rows = db.scalars(stmt.limit(200)).all()
    if viewer == "CAREGIVER":
        audit(db, actor_id=user.id, action="APPOINTMENTS_VIEWED_BY_CAREGIVER", entity_type="patient",
              entity_id=patient.id, request_id=request_id_of(request))
        db.commit()
    return ok(request, [_view(db, user, a, viewer) for a in rows], total=len(rows))


@router.get("/appointments/{appointment_id}")
def get_appointment(
    appointment_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    appt = booking.get_appointment(db, appointment_id)
    viewer = access.appointment_viewer(db, user, appt, PERM_VIEW_APPOINTMENTS)
    return ok(request, _view(db, user, appt, viewer))


@router.post("/appointments/{appointment_id}/cancel")
def cancel(
    appointment_id: uuid.UUID,
    body: CancelIn,
    request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)),
    db: Session = Depends(get_db),
):
    appt = booking.get_appointment(db, appointment_id)
    viewer = access.appointment_viewer(db, user, appt, PERM_CANCEL_APPOINTMENTS)
    appt = booking.cancel(db, actor=user, appointment_id=appt.id, reason=body.reason, request_id=request_id_of(request))
    return ok(request, _view(db, user, appt, viewer))


@router.post("/appointments/{appointment_id}/reschedule")
def reschedule(
    appointment_id: uuid.UUID,
    body: RescheduleIn,
    request: Request,
    idempotency_key: str | None = Header(default=None),
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)),
    db: Session = Depends(get_db),
):
    appt = booking.get_appointment(db, appointment_id)
    viewer = access.appointment_viewer(db, user, appt, PERM_RESCHEDULE_APPOINTMENTS)
    new = booking.reschedule(
        db,
        actor=user,
        appointment_id=appt.id,
        new_slot_id=body.new_slot_id,
        idempotency_key=_clean_key(idempotency_key),
        request_id=request_id_of(request),
    )
    return ok(request, _view(db, user, new, viewer))


# ------------------------------------------------------------------ doctor

@router.get("/doctor/appointments")
def doctor_appointments(
    request: Request,
    on_date: date | None = None,
    user: User = Depends(require_roles(ROLE_DOCTOR)),
    db: Session = Depends(get_db),
):
    doctor = access.doctor_of(db, user)
    if doctor is None:
        raise errors.not_found("Doctor")
    start, end = ist_day_bounds_utc(on_date or today_ist())
    rows = db.scalars(
        select(Appointment)
        .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .where(AppointmentSlot.doctor_id == doctor.id, ((Appointment.status == "PENDING") | ((AppointmentSlot.starts_at >= start) & (AppointmentSlot.starts_at < end))))
        .order_by(AppointmentSlot.starts_at)
    ).all()
    return ok(request, [_view(db, user, a, "DOCTOR") for a in rows], total=len(rows))


@router.post("/doctor/appointments/{appointment_id}/approve")
def approve_request(appointment_id: uuid.UUID, request: Request, user: User = Depends(require_roles(ROLE_DOCTOR)), db: Session = Depends(get_db)):
    appt = booking.get_appointment(db, appointment_id)
    if access.appointment_viewer(db, user, appt, None) != "DOCTOR":
        raise errors.not_found("Appointment")
    appt = booking.review_request(db, actor=user, appointment_id=appt.id, approve=True, request_id=request_id_of(request))
    return ok(request, _view(db, user, appt, "DOCTOR"))


@router.post("/doctor/appointments/{appointment_id}/reject")
def reject_request(appointment_id: uuid.UUID, request: Request, user: User = Depends(require_roles(ROLE_DOCTOR)), db: Session = Depends(get_db)):
    appt = booking.get_appointment(db, appointment_id)
    if access.appointment_viewer(db, user, appt, None) != "DOCTOR":
        raise errors.not_found("Appointment")
    appt = booking.review_request(db, actor=user, appointment_id=appt.id, approve=False, request_id=request_id_of(request))
    return ok(request, _view(db, user, appt, "DOCTOR"))


def _outcome(appointment_id, outcome, request, user, db):
    appt = booking.get_appointment(db, appointment_id)
    viewer = access.appointment_viewer(db, user, appt, None)
    if viewer not in ("DOCTOR", "ADMIN"):
        raise errors.not_found("Appointment")
    appt = booking.mark_outcome(db, actor=user, appointment_id=appt.id, outcome=outcome, request_id=request_id_of(request))
    return ok(request, _view(db, user, appt, viewer))


@router.post("/appointments/{appointment_id}/complete")
def complete(appointment_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _outcome(appointment_id, APPT_COMPLETED, request, user, db)


@router.post("/appointments/{appointment_id}/no-show")
def no_show(appointment_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _outcome(appointment_id, APPT_NO_SHOW, request, user, db)


# ------------------------------------------------------------------ pre-consultation and follow-up

@router.get("/appointments/{appointment_id}/intake")
def get_intake(appointment_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    appt = booking.get_appointment(db, appointment_id)
    return ok(request, clinical.get_intake(db, user, appt, request_id_of(request)))


@router.put("/appointments/{appointment_id}/intake")
def put_intake(
    appointment_id: uuid.UUID, body: IntakeIn, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    appt = booking.get_appointment(db, appointment_id)
    return ok(request, clinical.put_intake(db, user, appt, body.answers))


@router.post("/appointments/{appointment_id}/summary", status_code=201)
def create_summary(appointment_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    appt = booking.get_appointment(db, appointment_id)
    return ok(request, clinical.generate_summary(db, user, appt, user.preferred_language))


@router.get("/appointments/{appointment_id}/summary")
def get_summary(appointment_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    appt = booking.get_appointment(db, appointment_id)
    return ok(request, clinical.get_summary(db, user, appt))


@router.patch("/appointments/{appointment_id}/summary")
def patch_summary(
    appointment_id: uuid.UUID, body: SummaryPatchIn, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    appt = booking.get_appointment(db, appointment_id)
    return ok(
        request,
        clinical.patch_summary(
            db, user, appt, content=body.content, mark_reviewed=body.mark_reviewed,
            clinician_correction=body.clinician_correction,
        ),
    )


@router.get("/appointments/{appointment_id}/notes")
def get_notes(appointment_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    appt = booking.get_appointment(db, appointment_id)
    return ok(request, clinical.get_notes(db, user, appt))


@router.put("/appointments/{appointment_id}/notes")
def put_notes(
    appointment_id: uuid.UUID, body: NoteIn, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    appt = booking.get_appointment(db, appointment_id)
    return ok(request, clinical.put_notes(db, user, appt, body.note_text.strip(), request_id_of(request)))


@router.get("/appointments/{appointment_id}/follow-up")
def get_follow_up(appointment_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    appt = booking.get_appointment(db, appointment_id)
    return ok(request, clinical.get_follow_up(db, user, appt, request_id_of(request)))


@router.put("/appointments/{appointment_id}/follow-up")
def put_follow_up(
    appointment_id: uuid.UUID, body: FollowUpIn, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    appt = booking.get_appointment(db, appointment_id)
    return ok(
        request,
        clinical.put_follow_up(db, user, appt, body.instructions_text.strip(), body.next_visit_date, request_id_of(request)),
    )


# ------------------------------------------------------------------ waiting list

def _entry_out(entry: WaitingListEntry) -> dict:
    return {
        "id": entry.id,
        "status": entry.status,
        "patient_id": entry.patient_id,
        "created_at": to_utc_iso(entry.created_at),
        "doctor": affiliation_out(entry.affiliation),
    }


def _offer_out(offer: WaitingListOffer) -> dict:
    entry = offer.entry
    aff = entry.affiliation
    return {
        "id": offer.id,
        "entry_id": entry.id,
        "patient_id": entry.patient_id,
        "status": offer.status,
        "expires_at": to_utc_iso(offer.expires_at),
        "slot": slot_out(offer.slot),
        "doctor_name": aff.doctor.user.full_name,
        "hospital_name": aff.hospital.name,
    }


@router.post("/waiting-list", status_code=201)
def join_waiting_list(
    body: WaitlistIn, request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)), db: Session = Depends(get_db),
):
    patient = access.require_patient_access(db, user, body.patient_id, PERM_BOOK_APPOINTMENTS)
    entry = waitlist.join(db, actor=user, patient=patient, affiliation_id=body.affiliation_id,
                          request_id=request_id_of(request))
    return ok(request, _entry_out(entry))


@router.get("/waiting-list")
def get_waiting_list(
    patient_id: uuid.UUID, request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)), db: Session = Depends(get_db),
):
    patient = access.require_patient_access(db, user, patient_id, PERM_BOOK_APPOINTMENTS)
    entries = db.scalars(
        select(WaitingListEntry)
        .where(WaitingListEntry.patient_id == patient.id, WaitingListEntry.status.in_((WAIT_ACTIVE, WAIT_OFFERED)))
        .order_by(WaitingListEntry.created_at)
    ).all()
    offers = db.scalars(
        select(WaitingListOffer)
        .join(WaitingListEntry, WaitingListEntry.id == WaitingListOffer.entry_id)
        .where(
            WaitingListEntry.patient_id == patient.id,
            WaitingListOffer.status == OFFER_OPEN,
            WaitingListOffer.expires_at > utcnow(),
        )
    ).all()
    return ok(request, {"entries": [_entry_out(e) for e in entries], "offers": [_offer_out(o) for o in offers]})


@router.delete("/waiting-list/{entry_id}")
def leave_waiting_list(
    entry_id: uuid.UUID, request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)), db: Session = Depends(get_db),
):
    entry = db.get(WaitingListEntry, entry_id)
    if entry is None:
        raise errors.not_found("Waiting list entry")
    access.require_patient_access(db, user, entry.patient_id, PERM_BOOK_APPOINTMENTS)
    waitlist.leave(db, actor=user, entry=entry, request_id=request_id_of(request))
    return ok(request, {"left": True})


def _offer_for(db: Session, user: User, offer_id: uuid.UUID) -> WaitingListOffer:
    offer = db.get(WaitingListOffer, offer_id)
    if offer is None:
        raise errors.not_found("Offer")
    access.require_patient_access(db, user, offer.entry.patient_id, PERM_BOOK_APPOINTMENTS)
    return offer


@router.post("/waiting-list/offers/{offer_id}/accept", status_code=201)
def accept_offer(
    offer_id: uuid.UUID, request: Request,
    idempotency_key: str | None = Header(default=None),
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)), db: Session = Depends(get_db),
):
    offer = _offer_for(db, user, offer_id)
    appt = waitlist.accept(db, actor=user, offer_id=offer.id, idempotency_key=_clean_key(idempotency_key),
                           request_id=request_id_of(request))
    return ok(request, _view(db, user, appt, "SELF" if user.role == ROLE_PATIENT else "CAREGIVER"))


@router.post("/waiting-list/offers/{offer_id}/decline")
def decline_offer(
    offer_id: uuid.UUID, request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)), db: Session = Depends(get_db),
):
    offer = _offer_for(db, user, offer_id)
    waitlist.decline(db, actor=user, offer_id=offer.id, request_id=request_id_of(request))
    return ok(request, {"declined": True})
