"""Authentication, the current user's profile and in-app notifications."""
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.constants import ROLE_HOSPITAL_ADMIN, ROLE_PATIENT
from app.core import errors
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import client_ip, get_current_user
from app.core.errors import ok, request_id_of
from app.core.ratelimit import forgot_password_limiter, login_ip_limiter, login_limiter, register_limiter
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    hash_password_reset_token,
    new_password_reset_token,
    verify_password,
)
from app.core.timeutil import utcnow
from app.integrations import email as email_module
from app.models import Notification, PasswordResetToken, Patient, RefreshToken, User
from app.schemas import (
    ChangePasswordIn,
    ForgotPasswordIn,
    LoginIn,
    MeUpdateIn,
    RegisterIn,
    ResetPasswordIn,
    normalize_identifier,
)
from app.serializers import notification_out, user_out
from app.services import access
from app.services.common import audit

router = APIRouter()
REFRESH_COOKIE = "cb_refresh"
COOKIE_PATH = "/api/v1/auth"
# Verified against when the account does not exist, so both cases take similar time.
_DUMMY_HASH = hash_password("carebridge-dummy-password")


def me_payload(db: Session, user: User) -> dict:
    return user_out(
        user,
        patient=access.patient_of(db, user),
        doctor=access.doctor_of(db, user),
        hospital_ids=access.hospital_ids_of(db, user),
    )


def _set_refresh_cookie(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=COOKIE_PATH,
    )


def _issue_session(db: Session, user: User, response: Response, family_id: uuid.UUID | None = None) -> str:
    """Create a refresh token (cookie) and return a new access token. Does not commit."""
    settings = get_settings()
    raw, token_hash = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=token_hash,
            expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    _set_refresh_cookie(response, raw)
    return create_access_token(user.id)


def _find_user(db: Session, identifier: str) -> User | None:
    try:
        kind, value = normalize_identifier(identifier)
    except ValueError:
        return None
    column = User.phone if kind == "phone" else User.email
    return db.scalar(select(User).where(column == value))


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if not register_limiter.allow(client_ip(request)):
        raise errors.too_many_requests()
    kind, value = normalize_identifier(body.identifier)
    if _find_user(db, body.identifier) is not None:
        raise errors.conflict("IDENTIFIER_TAKEN", "An account with this phone number or email already exists.")
    user = User(
        full_name=body.full_name.strip(),
        phone=value if kind == "phone" else None,
        email=value if kind == "email" else None,
        password_hash=hash_password(body.password),
        role=body.role,
        preferred_language=body.preferred_language,
    )
    db.add(user)
    db.flush()
    if body.role == ROLE_PATIENT:
        db.add(Patient(user_id=user.id))
    audit(db, actor_id=user.id, action="USER_REGISTERED", entity_type="user", entity_id=user.id,
          request_id=request_id_of(request), meta={"role": body.role})
    access_token = _issue_session(db, user, response)
    db.commit()
    return ok(request, {"access_token": access_token, "user": me_payload(db, user)})


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ident, ip = body.identifier.strip().lower(), client_ip(request)
    if login_limiter.blocked(ident) or login_ip_limiter.blocked(ip):
        raise errors.too_many_requests()
    user = _find_user(db, body.identifier)
    password_ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if (
        user is None
        or not password_ok
        or not user.is_active
        or (
            user.role == ROLE_HOSPITAL_ADMIN
            and not access.has_approved_hospital(db, user)
        )
    ):
        login_limiter.allow(ident)  # only failed attempts count towards the limit
        login_ip_limiter.allow(ip)
        audit(db, actor_id=None, action="LOGIN_FAILED", entity_type="user", request_id=request_id_of(request))
        db.commit()
        # Same message whether the account exists or not.
        raise errors.AppError(401, "INVALID_CREDENTIALS", "Incorrect phone/email or password.")
    audit(db, actor_id=user.id, action="LOGIN_SUCCESS", entity_type="user", entity_id=user.id,
          request_id=request_id_of(request))
    access_token = _issue_session(db, user, response)
    db.commit()
    return ok(request, {"access_token": access_token, "user": me_payload(db, user)})


@router.post("/auth/forgot-password")
def forgot_password(body: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    """Always return the same response; delivery details are not disclosed."""
    ip = client_ip(request)
    email_key = body.email.strip().lower()
    if not forgot_password_limiter.allow(f"email:{email_key}") or not forgot_password_limiter.allow(f"ip:{ip}"):
        raise errors.too_many_requests()

    user = db.scalar(
        select(User).where(User.email == body.email, User.is_active.is_(True)).with_for_update()
    )
    raw_token = None
    if user is not None:
        now = utcnow()
        db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        raw_token, token_hash = new_password_reset_token()
        settings = get_settings()
        reset = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(minutes=settings.password_reset_expire_minutes),
        )
        db.add(reset)
        audit(
            db,
            actor_id=user.id,
            action="PASSWORD_RESET_REQUESTED",
            entity_type="user",
            entity_id=user.id,
            request_id=request_id_of(request),
        )
    db.commit()

    if user is not None and raw_token is not None:
        email_module.get_email().send_password_reset(user.email, raw_token)

    return ok(
        request,
        {"message": "If an account exists for that email, password reset instructions will be sent."},
    )


@router.post("/auth/reset-password")
def reset_password(body: ResetPasswordIn, request: Request, db: Session = Depends(get_db)):
    token_hash = hash_password_reset_token(body.token)
    reset = db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    ).scalar_one_or_none()
    now = utcnow()
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        raise errors.bad_request(
            "INVALID_RESET_TOKEN",
            "This password reset link is invalid or has expired.",
        )

    user = db.execute(
        select(User).where(User.id == reset.user_id).with_for_update()
    ).scalar_one_or_none()
    
    if (
            user is None
            or not user.is_active
            or (
                user.role == ROLE_HOSPITAL_ADMIN
                and not access.has_approved_hospital(db, user)
            )
        ):

        reset.used_at = now
        db.commit()
        raise errors.bad_request(
            "INVALID_RESET_TOKEN",
            "This password reset link is invalid or has expired.",
        )

    user.password_hash = hash_password(body.new_password)
    reset.used_at = now
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    audit(
        db,
        actor_id=user.id,
        action="PASSWORD_RESET_COMPLETED",
        entity_type="user",
        entity_id=user.id,
        request_id=request_id_of(request),
    )
    db.commit()
    return ok(request, {"password_reset": True})


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Rotate the refresh token. Reuse of an already-rotated token revokes the whole family."""
    if request.headers.get("x-requested-with", "").lower() != "carebridge":
        raise errors.forbidden("Missing required header")
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise errors.unauthorized("Not signed in")
    token = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)).with_for_update()
    ).scalar_one_or_none()
    now = utcnow()
    if token is None:
        raise errors.unauthorized("Not signed in")
    if token.revoked_at is not None:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        audit(db, actor_id=token.user_id, action="REFRESH_TOKEN_REUSE", entity_type="user", entity_id=token.user_id,
              request_id=request_id_of(request))
        db.commit()
        response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
        raise errors.unauthorized("Session ended. Please sign in again.")
    user = db.get(User, token.user_id)
    if (
                    token.expires_at <= now
                    or user is None
                    or not user.is_active
                    or (
                        user.role == ROLE_HOSPITAL_ADMIN
                        and not access.has_approved_hospital(db, user)
                    )
                ):
        raise errors.unauthorized("Session expired. Please sign in again.")
    token.revoked_at = now
    access_token = _issue_session(db, user, response, family_id=token.family_id)
    db.commit()
    return ok(request, {"access_token": access_token, "user": me_payload(db, user)})


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)))
        if token is not None:
            db.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            audit(db, actor_id=token.user_id, action="LOGOUT", entity_type="user", entity_id=token.user_id,
                  request_id=request_id_of(request))
            db.commit()
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return ok(request, {"signed_out": True})


@router.post("/auth/change-password")
def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise errors.bad_request("WRONG_PASSWORD", "The current password is not correct.")
    user.password_hash = hash_password(body.new_password)
    # Sign out every other device.
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    audit(db, actor_id=user.id, action="PASSWORD_CHANGED", entity_type="user", entity_id=user.id,
          request_id=request_id_of(request))
    access_token = _issue_session(db, user, response)
    db.commit()
    return ok(request, {"access_token": access_token})


@router.get("/me")
def get_me(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(request, me_payload(db, user))


@router.patch("/me")
def update_me(body: MeUpdateIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    if body.preferred_language is not None:
        user.preferred_language = body.preferred_language
    patient = access.patient_of(db, user)
    if patient is not None:
        fields = body.model_fields_set
        if "date_of_birth" in fields:
            patient.date_of_birth = body.date_of_birth
        if "sex" in fields:
            patient.sex = body.sex
        if "accessibility_notes" in fields:
            patient.accessibility_notes = body.accessibility_notes
    audit(db, actor_id=user.id, action="PROFILE_UPDATED", entity_type="user", entity_id=user.id,
          request_id=request_id_of(request))
    db.commit()
    return ok(request, me_payload(db, user))


@router.get("/me/notifications")
def list_notifications(
    request: Request, unread_only: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc()).limit(100)).all()
    unread = sum(1 for n in rows if n.read_at is None)
    return ok(request, [notification_out(n) for n in rows], unread=unread)


@router.post("/me/notifications/read-all")
def read_all_notifications(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(
        update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow())
    )
    db.commit()
    return ok(request, {"read": True})


@router.post("/me/notifications/{notification_id}/read")
def read_notification(
    notification_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise errors.not_found("Notification")
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return ok(request, notification_out(n))
