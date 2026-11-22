"""Audit log and in-app notification writers. Both write inside the caller's transaction."""
import uuid

from sqlalchemy.orm import Session

from app.constants import NOTIF_SENT
from app.models import AuditLog, Notification


def audit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id=None,
    hospital_id: uuid.UUID | None = None,
    request_id: str | None = None,
    meta: dict | None = None,
) -> None:
    """Record who did what. `meta` must only hold identifiers and status values."""
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            hospital_id=hospital_id,
            request_id=request_id,
            meta=meta or {},
        )
    )


def notify(db: Session, user_ids, type_: str, payload: dict) -> None:
    """Create one in-app notification per distinct user.

    An in-app notification is delivered by being stored, so it is written as SENT in the
    same transaction as the event it describes; a rollback removes it with the event.
    """
    for user_id in {u for u in user_ids if u is not None}:
        db.add(Notification(user_id=user_id, type=type_, payload=payload, status=NOTIF_SENT))
