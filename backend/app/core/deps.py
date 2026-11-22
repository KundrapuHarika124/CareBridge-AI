"""FastAPI dependencies: current user and role checks.

The access token carries only the user id. Role, hospital membership and caregiver
permissions are always read from the database for the request being served.
"""
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.constants import ROLE_HOSPITAL_ADMIN
from app.services import access
from app.core import errors
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise errors.unauthorized()
    user_id = decode_access_token(header[7:].strip())
    if user_id is None:
        raise errors.unauthorized("Session expired or invalid")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise errors.unauthorized("Session expired or invalid")

    if (
        user.role == ROLE_HOSPITAL_ADMIN
        and not access.has_approved_hospital(db, user)
    ):
        raise errors.forbidden("Your hospital is awaiting approval.")
    request.state.user_id = str(user.id)
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise errors.forbidden()
        return user

    return dependency


def client_ip(request: Request) -> str:
    # Do not trust X-Forwarded-For directly. A direct peer address is the only
    # caller-controlled source in this app; trusted reverse-proxy support should
    # be added only behind an explicitly configured proxy allow-list.
    return request.client.host if request.client else "unknown"
