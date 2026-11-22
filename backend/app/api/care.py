"""Caregiver access requests and patient consent decisions."""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.constants import ALL_PERMISSIONS, CONSENT_TEXT_VERSION, ROLE_CAREGIVER, ROLE_PATIENT
from app.core import errors
from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.core.errors import ok, request_id_of
from app.core.ratelimit import care_request_limiter
from app.models import User
from app.schemas import CareRequestIn, PermissionsIn, RevokeIn
from app.serializers import relationship_out
from app.services import care

router = APIRouter()


@router.get("/care/permissions")
def permission_catalog(request: Request, user: User = Depends(get_current_user)):
    return ok(request, {"permissions": list(ALL_PERMISSIONS), "consent_text_version": CONSENT_TEXT_VERSION})


@router.post("/care/requests", status_code=202)
def request_access(
    body: CareRequestIn,
    request: Request,
    user: User = Depends(require_roles(ROLE_CAREGIVER)),
    db: Session = Depends(get_db),
):
    if not care_request_limiter.allow(f"care:{user.id}"):
        raise errors.too_many_requests()
    care.request_access(
        db, caregiver=user, identifier=body.patient_identifier, permissions=body.permissions,
        request_id=request_id_of(request),
    )
    # Identical response whether or not the patient exists.
    return ok(request, {"submitted": True})


@router.get("/care/relationships")
def list_relationships(
    request: Request, user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)), db: Session = Depends(get_db)
):
    return ok(request, [relationship_out(rel, perms) for rel, perms in care.list_for(db, user)])


@router.post("/care/relationships/{relationship_id}/approve")
def approve(
    relationship_id: uuid.UUID,
    body: PermissionsIn,
    request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT)),
    db: Session = Depends(get_db),
):
    rel = care.approve(db, user=user, relationship_id=relationship_id, permissions=body.permissions,
                       request_id=request_id_of(request))
    return ok(request, relationship_out(rel, care.permissions_of(db, rel.id)))


@router.post("/care/relationships/{relationship_id}/reject")
def reject(
    relationship_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT)),
    db: Session = Depends(get_db),
):
    rel = care.reject(db, user=user, relationship_id=relationship_id, request_id=request_id_of(request))
    return ok(request, relationship_out(rel, []))


@router.patch("/care/relationships/{relationship_id}/permissions")
def modify(
    relationship_id: uuid.UUID,
    body: PermissionsIn,
    request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT)),
    db: Session = Depends(get_db),
):
    rel = care.modify(db, user=user, relationship_id=relationship_id, permissions=body.permissions,
                      request_id=request_id_of(request))
    return ok(request, relationship_out(rel, care.permissions_of(db, rel.id)))


@router.post("/care/relationships/{relationship_id}/revoke")
def revoke(
    relationship_id: uuid.UUID,
    body: RevokeIn,
    request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT)),
    db: Session = Depends(get_db),
):
    rel = care.revoke(db, user=user, relationship_id=relationship_id, reason=body.reason,
                      request_id=request_id_of(request))
    return ok(request, relationship_out(rel, []))


@router.get("/care/relationships/{relationship_id}/history")
def history(
    relationship_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_roles(ROLE_PATIENT, ROLE_CAREGIVER)),
    db: Session = Depends(get_db),
):
    return ok(request, care.history(db, user=user, relationship_id=relationship_id))
