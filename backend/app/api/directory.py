"""Hospitals, specialties, doctors, availability and specialty navigation (read-only)."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import errors
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.errors import ok
from app.core.timeutil import ist_day_bounds_utc
from app.models import Affiliation, Hospital, Specialty, User
from app.schemas import SuggestIn
from app.serializers import affiliation_out, hospital_out, slot_out, specialty_out
from app.services import directory, navigation

router = APIRouter()


@router.get("/specialties")
def specialties(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Specialty).order_by(Specialty.name_en)).all()
    return ok(request, [specialty_out(s) for s in rows])


@router.get("/hospitals")
def hospitals(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Hospital)
        .where(Hospital.is_approved.is_(True))
        .order_by(Hospital.name)
    ).all()
    return ok(request, [hospital_out(h) for h in rows])


@router.get("/hospitals/nearby")
def nearby_hospitals(
    request: Request,
    latitude: float = Query(..., description="Latitude in decimal degrees"),
    longitude: float = Query(..., description="Longitude in decimal degrees"),
    max_distance_km: float = Query(50.0, ge=1, le=500, description="Maximum distance in km"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Find hospitals near the given coordinates."""
    results = directory.nearby_hospitals(db, latitude, longitude, max_distance_km)
    return ok(request, results, total=len(results))


@router.get("/doctors/nearby")
def doctors_nearby(
    request: Request,
    latitude: float = Query(..., description="Latitude in decimal degrees"),
    longitude: float = Query(..., description="Longitude in decimal degrees"),
    max_distance_km: float = Query(50.0, ge=1, le=500, description="Maximum distance in km"),
    specialty_id: uuid.UUID | None = Query(None, description="Filter by specialty"),
    locality: str | None = Query(None, description="Filter by locality"),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Find doctors at hospitals near the given coordinates."""
    results = directory.search_doctors_nearby(
        db, latitude, longitude,
        specialty_id=specialty_id,
        locality=locality,
        max_distance_km=max_distance_km,
        limit=limit
    )
    return ok(request, results, total=len(results))


@router.get("/localities")
def localities(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(request, directory.localities(db))


@router.get("/doctors")
def doctors(
    request: Request,
    specialty_id: uuid.UUID | None = None,
    hospital_id: uuid.UUID | None = None,
    locality: str | None = None,
    q: str | None = None,
    on_date: date | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    results = directory.search_affiliations(
        db, specialty_id=specialty_id, hospital_id=hospital_id, locality=locality, q=q, on_date=on_date
    )
    return ok(request, [affiliation_out(aff, slots) for aff, slots in results], total=len(results))


@router.get("/affiliations/{affiliation_id}")
def affiliation(
    affiliation_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    aff = db.get(Affiliation, affiliation_id)
    if aff is None or not aff.is_active or not aff.hospital.is_approved:
        raise errors.not_found("Doctor")
    return ok(request, affiliation_out(aff, directory.available_slots(db, aff.id, limit=3)))


@router.get("/affiliations/{affiliation_id}/slots")
def slots(
    affiliation_id: uuid.UUID,
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    aff = db.get(Affiliation, affiliation_id)
    if aff is None or not aff.is_active or not aff.hospital.is_approved:
        raise errors.not_found("Doctor")
    start = ist_day_bounds_utc(date_from)[0] if date_from else None
    end = ist_day_bounds_utc(date_to)[1] if date_to else None
    found = directory.available_slots(db, aff.id, start=start, end=end)
    return ok(request, [slot_out(s) for s in found])


@router.get("/navigation/concerns")
def concerns(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(request, navigation.concerns(db))


@router.post("/navigation/suggest")
def suggest(body: SuggestIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not body.text and not body.concern_key:
        raise errors.bad_request("EMPTY_REQUEST", "Describe the concern or choose one.")
    return ok(request, navigation.suggest(db, text=body.text, concern_key=body.concern_key))
