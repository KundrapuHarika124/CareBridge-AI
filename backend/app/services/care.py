"""Caregiver relationships, granular permissions and the consent history."""
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.constants import (
    CONSENT_TEXT_VERSION,
    REL_ACTIVE,
    REL_REJECTED,
    REL_REQUESTED,
    REL_REVOKED,
    ROLE_CAREGIVER,
    ROLE_PATIENT,
)
from app.core import errors
from app.core.timeutil import to_utc_iso, utcnow
from app.models import CaregiverPermission, CareRelationship, ConsentRecord, Patient, User
from app.schemas import normalize_identifier
from app.services import access
from app.services.common import audit, notify


def permissions_of(db: Session, relationship_id: uuid.UUID) -> list[str]:
    return list(
        db.scalars(select(CaregiverPermission.permission).where(CaregiverPermission.relationship_id == relationship_id))
    )


def _record(db: Session, rel: CareRelationship, actor: User, action: str, permissions: list[str]) -> None:
    db.add(
        ConsentRecord(
            relationship_id=rel.id,
            actor_user_id=actor.id,
            action=action,
            permissions_snapshot=sorted(permissions),
            consent_text_version=CONSENT_TEXT_VERSION,
        )
    )


def request_access(db: Session, *, caregiver: User, identifier: str, permissions: list[str], request_id=None) -> None:
    """Ask a patient for access. Silent when the patient is unknown, so that this endpoint
    cannot be used to discover which phone numbers or emails have accounts."""
    kind, value = normalize_identifier(identifier)
    column = User.phone if kind == "phone" else User.email
    target = db.scalar(select(User).where(column == value, User.role == ROLE_PATIENT, User.is_active.is_(True)))
    if target is None:
        return
    patient = db.scalar(select(Patient).where(Patient.user_id == target.id))
    if patient is None:
        return
    open_rel = db.scalar(
        select(CareRelationship).where(
            CareRelationship.caregiver_user_id == caregiver.id,
            CareRelationship.patient_id == patient.id,
            CareRelationship.status.in_((REL_REQUESTED, REL_ACTIVE)),
        )
    )
    if open_rel is not None:
        return
    rel = CareRelationship(
        caregiver_user_id=caregiver.id, patient_id=patient.id, status=REL_REQUESTED, requested_permissions=permissions
    )
    db.add(rel)
    db.flush()
    _record(db, rel, caregiver, "REQUESTED", permissions)
    audit(db, actor_id=caregiver.id, action="CARE_ACCESS_REQUESTED", entity_type="care_relationship",
          entity_id=rel.id, request_id=request_id)
    notify(db, [target.id], "CARE_REQUEST", {"relationship_id": str(rel.id), "caregiver_name": caregiver.full_name})
    db.commit()


def list_for(db: Session, user: User) -> list[tuple[CareRelationship, list[str]]]:
    if user.role == ROLE_PATIENT:
        patient = access.patient_of(db, user)
        if patient is None:
            return []
        stmt = select(CareRelationship).where(
            CareRelationship.patient_id == patient.id, CareRelationship.status.in_((REL_REQUESTED, REL_ACTIVE))
        )
    elif user.role == ROLE_CAREGIVER:
        stmt = select(CareRelationship).where(CareRelationship.caregiver_user_id == user.id)
    else:
        return []
    rels = db.scalars(stmt.order_by(CareRelationship.requested_at.desc())).all()
    return [(rel, permissions_of(db, rel.id) if rel.status == REL_ACTIVE else []) for rel in rels]


def _owned_by_patient(db: Session, user: User, relationship_id: uuid.UUID) -> CareRelationship:
    """Only the patient the relationship is about may decide on it."""
    patient = access.patient_of(db, user)
    rel = db.execute(
        select(CareRelationship)
        .where(CareRelationship.id == relationship_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if rel is None or patient is None or rel.patient_id != patient.id:
        db.rollback()
        raise errors.not_found("Request")
    return rel


def _set_permissions(db: Session, rel: CareRelationship, permissions: list[str]) -> None:
    db.execute(delete(CaregiverPermission).where(CaregiverPermission.relationship_id == rel.id))
    for permission in permissions:
        db.add(CaregiverPermission(relationship_id=rel.id, permission=permission))


def approve(db: Session, *, user: User, relationship_id: uuid.UUID, permissions: list[str], request_id=None):
    rel = _owned_by_patient(db, user, relationship_id)
    if rel.status != REL_REQUESTED:
        db.rollback()
        raise errors.conflict("INVALID_STATUS", "This request has already been decided.")
    if not permissions:
        db.rollback()
        raise errors.bad_request("NO_PERMISSIONS", "Choose at least one permission, or reject the request.")
    rel.status = REL_ACTIVE
    rel.decided_at = utcnow()
    _set_permissions(db, rel, permissions)
    _record(db, rel, user, "GRANTED", permissions)
    audit(db, actor_id=user.id, action="CARE_ACCESS_GRANTED", entity_type="care_relationship", entity_id=rel.id,
          request_id=request_id, meta={"permissions": permissions})
    notify(db, [rel.caregiver_user_id], "CARE_APPROVED", {"relationship_id": str(rel.id), "patient_name": user.full_name})
    db.commit()
    return rel


def reject(db: Session, *, user: User, relationship_id: uuid.UUID, request_id=None):
    rel = _owned_by_patient(db, user, relationship_id)
    if rel.status != REL_REQUESTED:
        db.rollback()
        raise errors.conflict("INVALID_STATUS", "This request has already been decided.")
    rel.status = REL_REJECTED
    rel.decided_at = utcnow()
    _record(db, rel, user, "REJECTED", [])
    audit(db, actor_id=user.id, action="CARE_ACCESS_REJECTED", entity_type="care_relationship", entity_id=rel.id,
          request_id=request_id)
    notify(db, [rel.caregiver_user_id], "CARE_REJECTED", {"relationship_id": str(rel.id)})
    db.commit()
    return rel


def modify(db: Session, *, user: User, relationship_id: uuid.UUID, permissions: list[str], request_id=None):
    rel = _owned_by_patient(db, user, relationship_id)
    if rel.status != REL_ACTIVE:
        db.rollback()
        raise errors.conflict("INVALID_STATUS", "Only active access can be changed.")
    if not permissions:
        db.rollback()
        raise errors.bad_request("NO_PERMISSIONS", "To remove all permissions, remove this caregiver's access.")
    _set_permissions(db, rel, permissions)
    _record(db, rel, user, "MODIFIED", permissions)
    audit(db, actor_id=user.id, action="CARE_ACCESS_MODIFIED", entity_type="care_relationship", entity_id=rel.id,
          request_id=request_id, meta={"permissions": permissions})
    notify(db, [rel.caregiver_user_id], "CARE_MODIFIED", {"relationship_id": str(rel.id), "patient_name": user.full_name})
    db.commit()
    return rel


def revoke(db: Session, *, user: User, relationship_id: uuid.UUID, reason: str | None, request_id=None):
    rel = _owned_by_patient(db, user, relationship_id)
    if rel.status != REL_ACTIVE:
        db.rollback()
        raise errors.conflict("INVALID_STATUS", "Only active access can be removed.")
    rel.status = REL_REVOKED
    rel.revoked_at = utcnow()
    rel.revoke_reason = (reason or "").strip() or None
    _set_permissions(db, rel, [])
    _record(db, rel, user, "REVOKED", [])
    audit(db, actor_id=user.id, action="CARE_ACCESS_REVOKED", entity_type="care_relationship", entity_id=rel.id,
          request_id=request_id)
    notify(db, [rel.caregiver_user_id], "CARE_REVOKED", {"relationship_id": str(rel.id), "patient_name": user.full_name})
    db.commit()
    return rel


def history(db: Session, *, user: User, relationship_id: uuid.UUID) -> list[dict]:
    rel = db.get(CareRelationship, relationship_id)
    patient = access.patient_of(db, user)
    is_patient = rel is not None and patient is not None and rel.patient_id == patient.id
    is_caregiver = rel is not None and rel.caregiver_user_id == user.id
    if not (is_patient or is_caregiver):
        raise errors.not_found("Request")
    rows = db.scalars(
        select(ConsentRecord).where(ConsentRecord.relationship_id == rel.id).order_by(ConsentRecord.created_at)
    )
    return [
        {
            "action": r.action,
            "permissions": r.permissions_snapshot,
            "consent_text_version": r.consent_text_version,
            "actor_user_id": r.actor_user_id,
            "created_at": to_utc_iso(r.created_at),
        }
        for r in rows
    ]


def authorized_patients(db: Session, caregiver: User, permission: str | None = None) -> list[dict]:
    """Patients this caregiver currently has ACTIVE access to (optionally with one permission)."""
    out = []
    for rel in db.scalars(
        select(CareRelationship).where(
            CareRelationship.caregiver_user_id == caregiver.id, CareRelationship.status == REL_ACTIVE
        )
    ):
        perms = permissions_of(db, rel.id)
        if permission is None or permission in perms:
            out.append({"patient_id": rel.patient_id, "full_name": rel.patient.user.full_name, "permissions": sorted(perms)})
    return out
