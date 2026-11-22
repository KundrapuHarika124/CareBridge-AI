"""Database-backed side of the booking assistant: sessions, safety checks, booking."""
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    CONFIRM_TOKEN_MINUTES,
    PERM_BOOK_APPOINTMENTS,
    ROLE_CAREGIVER,
    ROLE_PATIENT,
    SESSION_IDLE_MINUTES,
    ST_AWAITING_CONFIRMATION,
    ST_BOOKED,
    ST_CANCELLED,
    TERMINAL_STATES,
    VOICE_CONFIDENCE_THRESHOLD,
)
from app.core import errors
from app.core.timeutil import to_utc_iso, today_ist, utcnow
from app.i18n.templates import t
from app.integrations import llm as llm_module
from app.models import ConversationMessage, ConversationSession, Specialty, User
from app.serializers import appointment_out
from app.services import access, assistant_core as core, booking, care, directory, navigation, safety


class _Port:
    """What the state machine may know and choose from, for one user."""

    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user
        self.is_caregiver = user.role == ROLE_CAREGIVER
        self._specialties = None
        self._localities = None

    def authorized_patients(self) -> list[dict]:
        if self.is_caregiver:
            return [
                {"id": str(p["patient_id"]), "name": p["full_name"]}
                for p in care.authorized_patients(self.db, self.user, PERM_BOOK_APPOINTMENTS)
            ]
        patient = access.patient_of(self.db, self.user)
        return [{"id": str(patient.id), "name": self.user.full_name}] if patient else []

    def specialties(self) -> list[dict]:
        if self._specialties is None:
            rows = self.db.scalars(select(Specialty).order_by(Specialty.name_en))
            self._specialties = [
                {"id": str(s.id), "code": s.code, "name_en": s.name_en, "name_te": s.name_te} for s in rows
            ]
        return self._specialties

    def suggest(self, text: str) -> list[dict]:
        found = navigation.suggest(self.db, text=text)["suggestions"]
        return [
            {
                "specialty_id": str(s["specialty"]["id"]),
                "explanation_en": s["explanation_en"],
                "explanation_te": s["explanation_te"],
            }
            for s in found
        ]

    def localities(self) -> list[str]:
        if self._localities is None:
            self._localities = directory.localities(self.db)
        return self._localities

    def search(self, specialty_id, locality, on_date, tod) -> list[dict]:
        slots = directory.find_slot_options(
            self.db, specialty_id=uuid.UUID(specialty_id), locality=locality, on_date=on_date, tod=tod
        )
        out = []
        for slot in slots:
            aff = slot.affiliation
            out.append(
                {
                    "slot_id": str(slot.id),
                    "doctor": aff.doctor.user.full_name,
                    "hospital": aff.hospital.name,
                    "locality": aff.hospital.locality,
                    "starts_at": slot.starts_at,
                }
            )
        return out


def _load(db: Session, user: User, session_id: uuid.UUID) -> ConversationSession:
    sess = db.get(ConversationSession, session_id)
    if sess is None or sess.user_id != user.id:
        raise errors.not_found("Conversation")
    return sess


def _add_message(db: Session, sess: ConversationSession, role: str, body: str, mode=None, confidence=None) -> None:
    last = db.scalar(select(func.max(ConversationMessage.seq)).where(ConversationMessage.session_id == sess.id)) or 0
    db.add(
        ConversationMessage(
            session_id=sess.id, seq=last + 1, role=role, body=body[:2000], input_mode=mode, stt_confidence=confidence
        )
    )
    db.flush()


def _response(sess, reply, options, *, ai_used=False, emergency=False, appointment=None) -> dict:
    data = sess.data or {}
    confirmation = None
    if sess.state == ST_AWAITING_CONFIRMATION and data.get("confirm") and data.get("slot"):
        confirmation = {
            "token": data["confirm"]["token"],
            "expires_at": data["confirm"]["expires_at"],
            "slot": data["slot"],
            "patient_name": data.get("patient_name"),
        }
    return {
        "session_id": sess.id,
        "state": sess.state,
        "language": sess.language,
        "reply": reply,
        "options": options,
        "confirmation": confirmation,
        "appointment": appointment,
        "ai_used": ai_used,
        "emergency": emergency,
        "ended": sess.state in TERMINAL_STATES,
    }


def _issue_confirmation(data: dict) -> None:
    """Server-issued token tying a confirmation to exactly one slot for a few minutes."""
    data["confirm"] = {
        "token": secrets.token_urlsafe(24),
        "slot_id": data["slot"]["slot_id"],
        "expires_at": to_utc_iso(utcnow() + timedelta(minutes=CONFIRM_TOKEN_MINUTES)),
    }


def _save(db: Session, sess: ConversationSession, data: dict, state: str) -> None:
    if state == ST_AWAITING_CONFIRMATION and data.get("slot"):
        current = data.get("confirm")
        if not current or current.get("slot_id") != data["slot"]["slot_id"]:
            _issue_confirmation(data)
    else:
        data.pop("confirm", None)
    sess.data = dict(data)  # reassign so the JSONB change is detected
    sess.state = state
    sess.turn_seq = (sess.turn_seq or 0) + 1
    sess.expires_at = utcnow() + timedelta(minutes=SESSION_IDLE_MINUTES)
    if data.get("patient_id"):
        sess.patient_id = uuid.UUID(data["patient_id"])


def create_session(db: Session, user: User, language: str, patient_id: uuid.UUID | None) -> dict:
    if user.role not in (ROLE_PATIENT, ROLE_CAREGIVER):
        raise errors.forbidden()
    port = _Port(db, user)
    data = core.new_data()
    if user.role == ROLE_PATIENT:
        patients = port.authorized_patients()
        if patients:
            data["patient_id"], data["patient_name"] = patients[0]["id"], patients[0]["name"]
    elif patient_id is not None:
        core.apply_move(data, f"patient:{patient_id}", port)  # ignored unless booking is permitted
    state, reply, options = core.next_prompt(data, language, port, today_ist())
    data["options"] = options
    sess = ConversationSession(
        user_id=user.id, state=state, language=language, data={}, expires_at=utcnow(), turn_seq=0
    )
    db.add(sess)
    db.flush()
    _save(db, sess, data, state)
    reply = t(language, "greet", name=user.full_name) + " " + reply
    _add_message(db, sess, "ASSISTANT", reply)
    db.commit()
    return _response(sess, reply, options)


def _not_past(iso: str | None) -> bool:
    if not iso:
        return False
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")) > utcnow()
    except ValueError:
        return False


def _expired(sess: ConversationSession) -> bool:
    return sess.expires_at <= utcnow() or sess.state in TERMINAL_STATES


def _book(db: Session, user: User, sess: ConversationSession, data: dict, port: _Port, request_id: str | None) -> dict:
    """Perform the booking the user confirmed. Authorization is checked again here."""
    lang = sess.language
    session_id = sess.id
    slot_id = uuid.UUID(data["slot"]["slot_id"])
    try:
        patient = access.require_patient_access(db, user, uuid.UUID(data["patient_id"]), PERM_BOOK_APPOINTMENTS)
        appt = booking.book(
            db,
            actor=user,
            patient=patient,
            slot_id=slot_id,
            reason=data.get("concern_text"),
            idempotency_key=f"asst:{session_id}:{slot_id}",
            request_id=request_id,
        )
    except errors.AppError as exc:
        db.rollback()
        sess = _load(db, user, session_id)
        data["slot"] = None
        data["slot_options"] = []
        note = "slot_taken" if exc.code == "SLOT_UNAVAILABLE" else "booking_failed"
        if exc.code == "NOT_FOUND":
            # Permission was withdrawn mid-conversation: stop instead of offering more slots.
            reply = t(lang, "no_patients")
            data["options"] = []
            _save(db, sess, data, ST_CANCELLED)
            _add_message(db, sess, "ASSISTANT", reply)
            db.commit()
            return _response(sess, reply, [])
        state, prompt, options = core.next_prompt(data, lang, port, today_ist())
        data["options"] = options
        reply = t(lang, note) + " " + prompt
        _save(db, sess, data, state)
        _add_message(db, sess, "ASSISTANT", reply)
        db.commit()
        return _response(sess, reply, options)

    sess = _load(db, user, session_id)
    reply = core.confirmation_text(data, lang, key="booked")
    data["options"] = []
    _save(db, sess, data, ST_BOOKED)
    _add_message(db, sess, "ASSISTANT", reply)
    db.commit()
    return _response(sess, reply, [], appointment=appointment_out(appt))


def turn(db: Session, user: User, session_id: uuid.UUID, body, request_id: str | None = None) -> dict:
    sess = _load(db, user, session_id)
    if body.language:
        sess.language = body.language
    lang = sess.language
    if _expired(sess):
        reply = t(lang, "expired")
        return _response(sess, reply, []) | {"ended": True, "state": ST_CANCELLED}

    port = _Port(db, user)
    data = dict(sess.data or {})
    text = (body.text or "").strip()
    move = (body.option_value or "").strip() or None
    if not text and not move:
        raise errors.bad_request("EMPTY_TURN", "Say or type something, or choose an option.")
    if text:
        _add_message(db, sess, "USER", text, body.input_mode, body.stt_confidence)
    else:
        _add_message(db, sess, "USER", f"[{move.split(':')[0]}]", "BUTTON")

    restart = {"label": t(lang, "opt_restart"), "value": "restart"}

    # 1. Safety checks run on the raw text before anything else, with fixed replies.
    if text and not data.get("emergency_ack") and safety.is_emergency(text):
        options = [{"label": t(lang, "opt_not_emergency"), "value": "ack_not_emergency"}, restart]
        data["options"] = options
        reply = t(lang, "emergency")
        _save(db, sess, data, sess.state)
        _add_message(db, sess, "ASSISTANT", reply)
        db.commit()
        return _response(sess, reply, options, emergency=True)
    if text and safety.asks_medical_advice(text):
        state, prompt, options = core.next_prompt(data, lang, port, today_ist())
        data["options"] = options
        reply = t(lang, "medical_advice") + " " + prompt
        _save(db, sess, data, state)
        _add_message(db, sess, "ASSISTANT", reply)
        db.commit()
        return _response(sess, reply, options)

    # 2. Understand the message: a button is already canonical; text goes through extraction.
    ai_used = False
    extraction = None
    if not move:
        context = {"specialties": port.specialties(), "localities": port.localities()}
        rules = core.extract_rules(text, context["specialties"], context["localities"])
        provider = llm_module.get_llm()
        extraction = rules
        if provider.available:
            try:
                raw = provider.extract(text, lang, sess.state, context)
                extraction = core.sanitize_extraction(raw)
                ai_used = True
                # A confirmation must come from an unmistakable yes/no word, never from the model.
                extraction.pop("yes_no", None)
                if "yes_no" in rules:
                    extraction["yes_no"] = rules["yes_no"]
                if "option_index" in rules:
                    extraction["option_index"] = rules["option_index"]
            except llm_module.LLMUnavailable:
                extraction = rules  # guided fallback; nothing is invented

    # 3. A spoken "yes" heard with low confidence never books.
    low_confidence = (
        body.input_mode == "VOICE"
        and body.stt_confidence is not None
        and body.stt_confidence < VOICE_CONFIDENCE_THRESHOLD
    )
    if low_confidence and sess.state == ST_AWAITING_CONFIRMATION:
        options = data.get("options") or []
        reply = t(lang, "tap_confirm")
        _save(db, sess, data, sess.state)
        _add_message(db, sess, "ASSISTANT", reply)
        db.commit()
        return _response(sess, reply, options, ai_used=ai_used)

    result = core.step(data, lang, sess.state, port, today_ist(), move=move, ex=extraction)
    if result.action == "BOOK":
        confirm = data.get("confirm") or {}
        if not data.get("slot") or confirm.get("slot_id") != data["slot"]["slot_id"]:
            raise errors.conflict("CONFIRMATION_INVALID", "Please choose a time again.")
        return _book(db, user, sess, data, port, request_id) | {"ai_used": ai_used}

    _save(db, sess, data, result.state)
    _add_message(db, sess, "ASSISTANT", result.reply)
    db.commit()
    return _response(sess, result.reply, result.options, ai_used=ai_used)


def confirm(db: Session, user: User, session_id: uuid.UUID, token: str, request_id: str | None = None) -> dict:
    """Book through the visible Confirm button, using the server-issued token."""
    sess = _load(db, user, session_id)
    data = dict(sess.data or {})
    pending = data.get("confirm") or {}
    valid = (
        not _expired(sess)
        and sess.state == ST_AWAITING_CONFIRMATION
        and data.get("slot")
        and secrets.compare_digest(str(pending.get("token", "")), token)
        and pending.get("slot_id") == data["slot"]["slot_id"]
        and _not_past(pending.get("expires_at"))
    )
    if not valid:
        raise errors.conflict("CONFIRMATION_INVALID", "This confirmation is no longer valid. Please choose a time again.")
    _add_message(db, sess, "USER", "[confirm]", "BUTTON")
    return _book(db, user, sess, data, _Port(db, user), request_id)


def status() -> dict:
    provider = llm_module.get_llm()
    return {
        "provider": provider.name,
        "status": provider.status(),
        "mode": "ai" if provider.available and provider.status() != "UNAVAILABLE" else "guided",
    }
