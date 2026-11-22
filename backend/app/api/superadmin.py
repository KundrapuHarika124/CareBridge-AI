
"""Super Admin (Platform Admin) endpoints for hospital onboarding and platform management.

Super Admin manages the platform at a high level:
- Approving/rejecting hospital applications
- Creating hospital admin accounts
- Viewing platform statistics
- Managing platform settings

Hospital admins manage their individual hospitals, doctors, and schedules.
"""
import time
import uuid

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    ROLE_CAREGIVER,
    ROLE_DOCTOR,
    ROLE_HOSPITAL_ADMIN,
    ROLE_PATIENT,
    ROLE_SUPER_ADMIN,
)
from app.core import errors
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.errors import ok
from app.core.security import hash_password
from app.core.timeutil import utcnow
from app.models import AuditLog, Hospital, HospitalStaff, User
from app.serializers import hospital_out
from app.services import waitlist

router = APIRouter(prefix="/admin")
_super = require_roles(ROLE_SUPER_ADMIN)


# ---------------------------------------------------------
# Hospital location search configuration
# ---------------------------------------------------------

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

NOMINATIM_USER_AGENT = (
    "CareBridgeAI/1.0 "
    "(hospital location search; contact:carebridgeai122@gmail.com)"
)

_location_cache: dict[str, tuple[float, list]] = {}
_last_location_request = 0.0


# ---------------------------------------------------------
# Request schemas
# ---------------------------------------------------------

class HospitalRegistrationIn(BaseModel):
    """Input for a new hospital registration (from Super Admin)."""

    name: str = Field(min_length=2, max_length=160)
    locality: str = Field(min_length=1, max_length=80)
    city: str = Field(min_length=1, max_length=80)
    address: str = Field(max_length=300, default="")
    phone: str = Field(max_length=30, default="")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    admin_name: str = Field(min_length=2, max_length=120)
    admin_email: str | None = Field(
        default=None,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    admin_password: str = Field(min_length=8, max_length=128)


class HospitalApproveIn(BaseModel):
    """Input for approving/rejecting a hospital."""

    is_approved: bool
    note: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------
# Hospital location search
# ---------------------------------------------------------

@router.get("/location-search")
def search_hospital_location(
    request: Request,
    q: str = Query(min_length=3, max_length=200),
    user: User = Depends(_super),
):
    """Search Indian addresses using OpenStreetMap Nominatim."""

    global _last_location_request

    search_text = q.strip()

    if len(search_text) < 3:
        raise HTTPException(
            status_code=422,
            detail="Please enter at least 3 characters.",
        )

    cache_key = search_text.lower()
    now = time.monotonic()

    # Reuse recent search results.
    cached = _location_cache.get(cache_key)

    if cached and now - cached[0] < 300:
        return ok(request, cached[1])

    # Respect Nominatim's one-request-per-second limit.
    if now - _last_location_request < 1.0:
        raise HTTPException(
            status_code=429,
            detail="Please wait a moment before searching again.",
        )

    _last_location_request = now

    try:
        response = httpx.get(
            NOMINATIM_URL,
            params={
                "q": search_text,
                "format": "jsonv2",
                "limit": 5,
                "countrycodes": "in",
                "addressdetails": 1,
            },
            headers={
                "User-Agent": NOMINATIM_USER_AGENT,
            },
            timeout=8.0,
        )

        response.raise_for_status()
        results = response.json()

    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Location search is temporarily unavailable.",
        )

    locations = [
        {
            "display_name": item["display_name"],
            "latitude": float(item["lat"]),
            "longitude": float(item["lon"]),
        }
        for item in results
        if (
            item.get("lat")
            and item.get("lon")
            and item.get("display_name")
        )
    ]

    _location_cache[cache_key] = (
        time.monotonic(),
        locations,
    )

    return ok(request, locations)


# ---------------------------------------------------------
# List hospitals
# ---------------------------------------------------------

@router.get("/hospitals")
def list_hospitals(
    request: Request,
    include_unapproved: bool = False,
    user: User = Depends(_super),
    db: Session = Depends(get_db),
):
    """List all hospitals (optionally only approved ones)."""

    stmt = select(Hospital).order_by(Hospital.name)

    if not include_unapproved:
        stmt = stmt.where(Hospital.is_approved.is_(True))

    rows = db.scalars(stmt).all()

    return ok(
        request,
        [hospital_out(h) for h in rows],
    )


# ---------------------------------------------------------
# Pending hospitals
# ---------------------------------------------------------

@router.get("/hospitals/pending")
def pending_hospitals(
    request: Request,
    user: User = Depends(_super),
    db: Session = Depends(get_db),
):
    """List hospitals pending approval."""

    rows = db.scalars(
        select(Hospital)
        .where(Hospital.is_approved.is_(False))
        .order_by(Hospital.name)
    ).all()

    return ok(
        request,
        [hospital_out(h) for h in rows],
    )


# ---------------------------------------------------------
# Create hospital
# ---------------------------------------------------------

@router.post("/hospitals", status_code=201)
def create_hospital(
    body: HospitalRegistrationIn,
    request: Request,
    user: User = Depends(_super),
    db: Session = Depends(get_db),
):
    """Create a new hospital and its administrator account."""

    # Check if hospital name already exists locally.
    exists = db.scalar(
        select(Hospital.id).where(
            func.lower(Hospital.name) == body.name.strip().lower()
        )
    )

    if exists:
        raise errors.conflict(
            "HOSPITAL_EXISTS",
            "A hospital with this name already exists.",
        )

    # Create hospital.
    hospital = Hospital(
        name=body.name.strip(),
        locality=body.locality.strip(),
        city=body.city.strip(),
        address=body.address.strip(),
        phone=body.phone.strip(),
        latitude=body.latitude,
        longitude=body.longitude,
        is_simulated=False,
        is_approved=False,
        approved_at=None,
    )

    db.add(hospital)
    db.flush()

    # Create hospital admin user.
    admin_user = User(
        full_name=body.admin_name.strip(),
        email=body.admin_email,
        password_hash=hash_password(body.admin_password),
        role=ROLE_HOSPITAL_ADMIN,
        preferred_language="en",
        is_active=True,
    )

    db.add(admin_user)
    db.flush()

    # Link admin to hospital.
    db.add(
        HospitalStaff(
            user_id=admin_user.id,
            hospital_id=hospital.id,
        )
    )

    # Audit log.
    audit_db(
        user,
        "HOSPITAL_CREATED",
        "hospital",
        hospital.id,
        request,
        db,
        {
            "name": hospital.name,
            "admin_id": str(admin_user.id),
        },
    )

    db.commit()

    return ok(
        request,
        {
            "hospital": hospital_out(hospital),
            "admin_email": body.admin_email,
        },
    )


# ---------------------------------------------------------
# Approve or reject hospital
# ---------------------------------------------------------

@router.patch("/hospitals/{hospital_id}")
def update_hospital(
    hospital_id: uuid.UUID,
    body: HospitalApproveIn,
    request: Request,
    user: User = Depends(_super),
    db: Session = Depends(get_db),
):
    """Approve or reject a hospital application."""

    hospital = db.execute(
        select(Hospital)
        .where(Hospital.id == hospital_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()

    if hospital is None:
        raise errors.not_found("Hospital")

    if hospital.is_approved == body.is_approved:
        raise errors.conflict(
            "INVALID_STATUS",
            f"Hospital is already "
            f"{'approved' if body.is_approved else 'pending'}",
        )

    if body.is_approved:
        hospital.is_approved = True
        hospital.approved_at = utcnow()

    else:
        waitlist.cleanup_rejected_hospital(
            db,
            hospital.id,
            hospital_locked=True,
        )

        hospital.is_approved = False
        hospital.approved_at = None

    audit_db(
        user,
        "HOSPITAL_APPROVED" if body.is_approved else "HOSPITAL_REJECTED",
        "hospital",
        hospital_id,
        request,
        db,
        {"note": body.note},
    )

    db.commit()

    return ok(request, hospital_out(hospital))


# ---------------------------------------------------------
# Delete hospital
# ---------------------------------------------------------

@router.delete("/hospitals/{hospital_id}")
def delete_hospital(
    hospital_id: uuid.UUID,
    request: Request,
    user: User = Depends(_super),
    db: Session = Depends(get_db),
):
    """Delete a hospital (Super Admin only)."""

    hospital = db.get(Hospital, hospital_id)

    if hospital is None:
        raise errors.not_found("Hospital")

    db.delete(hospital)

    audit_db(
        user,
        "HOSPITAL_DELETED",
        "hospital",
        hospital_id,
        request,
        db,
    )

    db.commit()

    return ok(request, {"deleted": True})


# ---------------------------------------------------------
# Platform statistics
# ---------------------------------------------------------

@router.get("/stats")
def platform_stats(
    request: Request,
    user: User = Depends(_super),
    db: Session = Depends(get_db),
):
    """Platform-level statistics."""

    stats = {
        "total_hospitals": db.scalar(
            select(func.count(Hospital.id))
        ) or 0,

        "approved_hospitals": db.scalar(
            select(func.count(Hospital.id)).where(
                Hospital.is_approved.is_(True)
            )
        ) or 0,

        "pending_hospitals": db.scalar(
            select(func.count(Hospital.id)).where(
                Hospital.is_approved.is_(False)
            )
        ) or 0,

        "total_users": db.scalar(
            select(func.count(User.id))
        ) or 0,

        "super_admins": db.scalar(
            select(func.count(User.id)).where(
                User.role == ROLE_SUPER_ADMIN
            )
        ) or 0,

        "hospital_admins": db.scalar(
            select(func.count(User.id)).where(
                User.role == ROLE_HOSPITAL_ADMIN
            )
        ) or 0,

        "doctors": db.scalar(
            select(func.count(User.id)).where(
                User.role == ROLE_DOCTOR
            )
        ) or 0,

        "patients": db.scalar(
            select(func.count(User.id)).where(
                User.role == ROLE_PATIENT
            )
        ) or 0,

        "caregivers": db.scalar(
            select(func.count(User.id)).where(
                User.role == ROLE_CAREGIVER
            )
        ) or 0,
    }

    return ok(request, stats)


# ---------------------------------------------------------
# Audit logging helper
# ---------------------------------------------------------

def audit_db(
    actor: User,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    request: Request,
    db: Session,
    meta: dict | None = None,
):
    """Create an audit log entry."""

    db.add(
        AuditLog(
            actor_user_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            request_id=request.headers.get("X-Request-ID", ""),
            meta=meta or {},
        )
    )
