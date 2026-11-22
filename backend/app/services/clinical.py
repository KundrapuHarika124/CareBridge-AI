"""Pre-consultation intake, AI summaries, clinician notes and follow-up instructions.

AI-generated content lives in consultation_summaries only. Clinician-authored content
lives in consultation_notes and follow_up_instructions. Hospital admins see none of it.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import (
    PERM_VIEW_FOLLOW_UP_INFORMATION,
    PERM_VIEW_PRECONSULTATION_INFORMATION,
)
from app.core import errors
from app.core.timeutil import to_utc_iso, utcnow
from app.integrations import llm as llm_module
from app.models import (
    Appointment,
    ConsultationNote,
    ConsultationSummary,
    FollowUpInstruction,
    Questionnaire,
    QuestionnaireResponse,
    User,
)
from app.services import access
from app.services.common import audit

SUMMARY_SECTIONS = (
    "reason_for_visit",
    "concerns",
    "duration",
    "other_information",
    "questions_for_doctor",
    "unclear_or_missing",
)


def _viewer(db: Session, user: User, appt: Appointment, permission: str | None, allowed: tuple[str, ...]) -> str:
    viewer = access.appointment_viewer(db, user, appt, permission)
    if viewer not in allowed:
        raise errors.not_found("Appointment")
    return viewer


def questionnaire_for(db: Session, appt: Appointment) -> Questionnaire | None:
    specialty_id = appt.slot.affiliation.specialty_id
    specific = db.scalar(
        select(Questionnaire)
        .where(Questionnaire.is_active.is_(True), Questionnaire.specialty_id == specialty_id)
        .order_by(Questionnaire.version.desc())
    )
    if specific:
        return specific
    return db.scalar(
        select(Questionnaire)
        .where(Questionnaire.is_active.is_(True), Questionnaire.specialty_id.is_(None))
        .order_by(Questionnaire.version.desc())
    )


def _response(db: Session, appt: Appointment) -> QuestionnaireResponse | None:
    return db.scalar(select(QuestionnaireResponse).where(QuestionnaireResponse.appointment_id == appt.id))


def _summary(db: Session, appt: Appointment) -> ConsultationSummary | None:
    return db.scalar(select(ConsultationSummary).where(ConsultationSummary.appointment_id == appt.id))


def get_intake(db: Session, user: User, appt: Appointment, request_id=None) -> dict:
    viewer = _viewer(db, user, appt, PERM_VIEW_PRECONSULTATION_INFORMATION, ("SELF", "CAREGIVER", "DOCTOR"))
    response = _response(db, appt)
    q = db.get(Questionnaire, response.questionnaire_id) if response else questionnaire_for(db, appt)
    if viewer == "CAREGIVER":
        audit(db, actor_id=user.id, action="INTAKE_VIEWED_BY_CAREGIVER", entity_type="appointment",
              entity_id=appt.id, request_id=request_id)
        db.commit()
    return {
        "questionnaire": None
        if q is None
        else {
            "id": q.id,
            "title_en": q.title_en,
            "title_te": q.title_te,
            "questions": q.questions,
            "review_status": q.review_status,
        },
        "answers": response.answers if response else {},
        "submitted_at": to_utc_iso(response.submitted_at) if response else None,
        "can_edit": viewer == "SELF",
    }


def put_intake(db: Session, user: User, appt: Appointment, answers: dict[str, str]) -> dict:
    _viewer(db, user, appt, None, ("SELF",))
    q = questionnaire_for(db, appt)
    if q is None:
        raise errors.not_found("Questionnaire")
    known = {item["key"] for item in q.questions}
    cleaned = {k: v.strip() for k, v in answers.items() if k in known and v.strip()}
    response = _response(db, appt)
    if response is None:
        response = QuestionnaireResponse(
            appointment_id=appt.id, questionnaire_id=q.id, answers=cleaned, submitted_by_user_id=user.id
        )
        db.add(response)
    else:
        response.answers = cleaned
        response.questionnaire_id = q.id
        response.submitted_at = utcnow()
    # Answers changed, so a summary written from the old answers is no longer valid.
    stale = _summary(db, appt)
    if stale is not None:
        db.delete(stale)
    db.commit()
    return get_intake(db, user, appt)


def summary_out(s: ConsultationSummary | None) -> dict | None:
    if s is None:
        return None
    return {
        "content": s.content,
        "source": s.source,
        "label": "AI-generated",
        "model_name": s.model_name,
        "created_at": to_utc_iso(s.created_at),
        "patient_edited": s.patient_edited,
        "patient_reviewed_at": to_utc_iso(s.patient_reviewed_at),
        "clinician_correction": s.clinician_correction,
    }


def generate_summary(db: Session, user: User, appt: Appointment, language: str) -> dict:
    """Patient asks for an AI summary of their own answers. Never fabricated: with no
    working model the call fails with AI_UNAVAILABLE and the doctor simply sees the raw answers."""
    _viewer(db, user, appt, None, ("SELF",))
    response = _response(db, appt)
    if response is None or not response.answers:
        raise errors.bad_request("NO_INTAKE", "Answer the questions first.")
    q = db.get(Questionnaire, response.questionnaire_id)
    pairs = [
        {"question": item.get("text_en", item["key"]), "answer": response.answers[item["key"]]}
        for item in q.questions
        if item["key"] in response.answers
    ]
    provider = llm_module.get_llm()
    try:
        sections = provider.summarize(pairs, language)
    except llm_module.LLMUnavailable:
        raise errors.unavailable("AI_UNAVAILABLE", "The AI summary is unavailable right now. Your answers are saved.")
    content = {key: str(sections.get(key, "") or "")[:2000] for key in SUMMARY_SECTIONS}
    summary = _summary(db, appt)
    if summary is None:
        summary = ConsultationSummary(appointment_id=appt.id, content=content, model_name=provider.model_name)
        db.add(summary)
    else:
        summary.content = content
        summary.model_name = provider.model_name
        summary.created_at = utcnow()
        summary.patient_edited = False
        summary.patient_reviewed_at = None
        summary.clinician_correction = None
    db.commit()
    return summary_out(summary)


def get_summary(db: Session, user: User, appt: Appointment) -> dict | None:
    viewer = _viewer(db, user, appt, PERM_VIEW_PRECONSULTATION_INFORMATION, ("SELF", "CAREGIVER", "DOCTOR"))
    summary = _summary(db, appt)
    # Release gate: nobody but the patient sees a summary the patient has not reviewed.
    if summary is not None and viewer != "SELF" and summary.patient_reviewed_at is None:
        return None
    return summary_out(summary)


def patch_summary(db: Session, user: User, appt: Appointment, *, content, mark_reviewed, clinician_correction):
    viewer = _viewer(db, user, appt, None, ("SELF", "DOCTOR"))
    summary = _summary(db, appt)
    if summary is None:
        raise errors.not_found("Summary")
    if viewer == "SELF":
        if content is not None:
            summary.content = {key: str(content.get(key, summary.content.get(key, "")))[:2000] for key in SUMMARY_SECTIONS}
            summary.patient_edited = True
        if mark_reviewed:
            summary.patient_reviewed_at = utcnow()
    else:
        if summary.patient_reviewed_at is None:
            raise errors.not_found("Summary")
        if clinician_correction is not None:
            summary.clinician_correction = clinician_correction.strip() or None
            audit(db, actor_id=user.id, action="SUMMARY_CORRECTED", entity_type="appointment", entity_id=appt.id)
    db.commit()
    return summary_out(summary)


def get_notes(db: Session, user: User, appt: Appointment) -> dict | None:
    _viewer(db, user, appt, None, ("DOCTOR",))
    note = db.scalar(select(ConsultationNote).where(ConsultationNote.appointment_id == appt.id))
    if note is None:
        return None
    return {"note_text": note.note_text, "updated_at": to_utc_iso(note.updated_at), "label": "Clinician-authored"}


def put_notes(db: Session, user: User, appt: Appointment, note_text: str, request_id=None) -> dict:
    _viewer(db, user, appt, None, ("DOCTOR",))
    doctor = access.doctor_of(db, user)
    note = db.scalar(select(ConsultationNote).where(ConsultationNote.appointment_id == appt.id))
    if note is None:
        note = ConsultationNote(appointment_id=appt.id, doctor_id=doctor.id, note_text=note_text)
        db.add(note)
    else:
        note.note_text = note_text
        note.updated_at = utcnow()
    audit(db, actor_id=user.id, action="NOTE_SAVED", entity_type="appointment", entity_id=appt.id,
          hospital_id=appt.slot.affiliation.hospital_id, request_id=request_id)
    db.commit()
    return get_notes(db, user, appt)


def follow_up_out(f: FollowUpInstruction | None) -> dict | None:
    if f is None:
        return None
    return {
        "instructions_text": f.instructions_text,
        "next_visit_date": f.next_visit_date.isoformat() if f.next_visit_date else None,
        "updated_at": to_utc_iso(f.updated_at),
        "label": "Clinician-authored",
    }


def get_follow_up(db: Session, user: User, appt: Appointment, request_id=None) -> dict | None:
    viewer = _viewer(db, user, appt, PERM_VIEW_FOLLOW_UP_INFORMATION, ("SELF", "CAREGIVER", "DOCTOR"))
    follow_up = db.scalar(select(FollowUpInstruction).where(FollowUpInstruction.appointment_id == appt.id))
    if viewer == "CAREGIVER" and follow_up is not None:
        audit(db, actor_id=user.id, action="FOLLOW_UP_VIEWED_BY_CAREGIVER", entity_type="appointment",
              entity_id=appt.id, request_id=request_id)
        db.commit()
    return follow_up_out(follow_up)


def put_follow_up(db: Session, user: User, appt: Appointment, text: str, next_visit_date, request_id=None) -> dict:
    from app.services.common import notify

    _viewer(db, user, appt, None, ("DOCTOR",))
    doctor = access.doctor_of(db, user)
    follow_up = db.scalar(select(FollowUpInstruction).where(FollowUpInstruction.appointment_id == appt.id))
    if follow_up is None:
        follow_up = FollowUpInstruction(
            appointment_id=appt.id, doctor_id=doctor.id, instructions_text=text, next_visit_date=next_visit_date
        )
        db.add(follow_up)
    else:
        follow_up.instructions_text = text
        follow_up.next_visit_date = next_visit_date
        follow_up.updated_at = utcnow()
    audit(db, actor_id=user.id, action="FOLLOW_UP_SAVED", entity_type="appointment", entity_id=appt.id,
          hospital_id=appt.slot.affiliation.hospital_id, request_id=request_id)
    notify(db, [appt.patient.user_id], "FOLLOW_UP_ADDED",
           {"appointment_id": str(appt.id), "doctor_name": user.full_name})
    db.commit()
    return follow_up_out(follow_up)
