"""Booking assistant (text and voice share these endpoints) and speech tokens."""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.constants import ROLE_CAREGIVER, ROLE_PATIENT
from app.core import errors
from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.core.errors import ok, request_id_of
from app.core.ratelimit import assistant_limiter, speech_token_limiter
from app.integrations import speech as speech_module
from app.models import User
from app.schemas import ConfirmIn, SessionCreateIn, TurnIn
from app.services import assistant

router = APIRouter()
_roles = require_roles(ROLE_PATIENT, ROLE_CAREGIVER)


@router.get("/assistant/status")
def assistant_status(request: Request, user: User = Depends(get_current_user)):
    return ok(request, assistant.status())


@router.post("/assistant/sessions", status_code=201)
def create_session(body: SessionCreateIn, request: Request, user: User = Depends(_roles), db: Session = Depends(get_db)):
    if not assistant_limiter.allow(f"assistant:{user.id}"):
        raise errors.too_many_requests()
    return ok(request, assistant.create_session(db, user, body.language, body.patient_id))


@router.post("/assistant/sessions/{session_id}/turns")
def turn(session_id: uuid.UUID, body: TurnIn, request: Request, user: User = Depends(_roles), db: Session = Depends(get_db)):
    if not assistant_limiter.allow(f"assistant:{user.id}"):
        raise errors.too_many_requests()
    return ok(request, assistant.turn(db, user, session_id, body, request_id_of(request)))


@router.post("/assistant/sessions/{session_id}/confirm")
def confirm(session_id: uuid.UUID, body: ConfirmIn, request: Request, user: User = Depends(_roles), db: Session = Depends(get_db)):
    return ok(request, assistant.confirm(db, user, session_id, body.token, request_id_of(request)))


@router.get("/speech/status")
def speech_status(request: Request, user: User = Depends(get_current_user)):
    provider = speech_module.get_speech()
    return ok(request, {"available": provider.available, "provider": provider.name})


@router.post("/speech/token")
def speech_token(request: Request, user: User = Depends(_roles)):
    provider = speech_module.get_speech()
    if not provider.available:
        raise errors.unavailable("SPEECH_UNAVAILABLE", "Voice is not available. Please type instead.")
    if not speech_token_limiter.allow(f"speech:{user.id}"):
        raise errors.too_many_requests()
    try:
        return ok(request, provider.issue_token())
    except speech_module.SpeechUnavailable:
        raise errors.unavailable("SPEECH_UNAVAILABLE", "Voice is not available right now. Please type instead.")
