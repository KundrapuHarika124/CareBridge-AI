"""Authorization decisions. Every route goes through these helpers.

Records outside the caller's scope raise NOT_FOUND (404) rather than FORBIDDEN so that
identifiers cannot be probed. Caregiver permissions are read from the database on every
call and are never cached or placed in tokens, so revocation applies to the next request.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import (
    REL_ACTIVE,
    ROLE_CAREGIVER,
    ROLE_DOCTOR,
    ROLE_HOSPITAL_ADMIN,
    ROLE_PATIENT,
)
from app.core import errors
from app.models import (
    Appointment,
    CaregiverPermission,
    CareRelationship,
    Doctor,
    Hospital,
    HospitalStaff,
    Patient,
    User,
)


def patient_of(db: Session, user: User) -> Patient | None:
    if user.role != ROLE_PATIENT:
        return None
    return db.scalar(select(Patient).where(Patient.user_id == user.id))


def doctor_of(db: Session, user: User) -> Doctor | None:
    if user.role != ROLE_DOCTOR:
        return None
    return db.scalar(select(Doctor).where(Doctor.user_id == user.id))


def has_approved_hospital(db: Session, user: User) -> bool:
    """Check whether a hospital admin belongs to at least one approved hospital."""
    return db.scalar(
        select(Hospital.id)
        .join(HospitalStaff, HospitalStaff.hospital_id == Hospital.id)
        .where(
            HospitalStaff.user_id == user.id,
            Hospital.is_approved.is_(True),
        )
        .limit(1)
    ) is not None
def hospital_ids_of(db: Session, user: User) -> list[uuid.UUID]:
    """Return hospital IDs linked to this hospital admin."""
    if user.role != ROLE_HOSPITAL_ADMIN:
        return []

    return list(
        db.scalars(
            select(HospitalStaff.hospital_id).where(
                HospitalStaff.user_id == user.id
            )
        )
    )

def caregiver_permissions(db: Session, caregiver_user_id: uuid.UUID, patient_id: uuid.UUID) -> set[str]:
    """Permissions currently granted to this caregiver for this patient (empty if none)."""
    rows = db.scalars(
        select(CaregiverPermission.permission)
        .join(CareRelationship, CareRelationship.id == CaregiverPermission.relationship_id)
        .where(
            CareRelationship.caregiver_user_id == caregiver_user_id,
            CareRelationship.patient_id == patient_id,
            CareRelationship.status == REL_ACTIVE,
        )
    )
    return set(rows)


def require_patient_access(db: Session, user: User, patient_id: uuid.UUID, permission: str | None) -> Patient:
    """Return the patient if `user` may act on it.

    The patient themself always passes. A caregiver passes only with `permission` granted.
    `permission=None` means the action is reserved for the patient personally.
    """
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise errors.not_found("Patient")
    if user.role == ROLE_PATIENT and patient.user_id == user.id:
        return patient
    if user.role == ROLE_CAREGIVER and permission is not None:
        if permission in caregiver_permissions(db, user.id, patient_id):
            return patient
    raise errors.not_found("Patient")


def require_hospital_admin(db: Session, user: User, hospital_id: uuid.UUID) -> None:
    hospital = db.get(Hospital, hospital_id)
    if (
        user.role != ROLE_HOSPITAL_ADMIN
        or hospital_id not in hospital_ids_of(db, user)
        or hospital is None
        or not hospital.is_approved
    ):
        raise errors.not_found("Hospital")


def appointment_viewer(db: Session, user: User, appt: Appointment, permission: str | None) -> str:
    """Return how `user` relates to the appointment: SELF, CAREGIVER, DOCTOR or ADMIN.

    Raises NOT_FOUND when the user has no relationship that allows access. `permission`
    is the caregiver permission the calling action requires (None: caregivers excluded).
    """
    if user.role == ROLE_PATIENT:
        patient = patient_of(db, user)
        if patient and patient.id == appt.patient_id:
            return "SELF"
    elif user.role == ROLE_CAREGIVER:
        if permission and permission in caregiver_permissions(db, user.id, appt.patient_id):
            return "CAREGIVER"
    elif user.role == ROLE_DOCTOR:
        doctor = doctor_of(db, user)
        if doctor and appt.slot.doctor_id == doctor.id:
            return "DOCTOR"
    elif user.role == ROLE_HOSPITAL_ADMIN:
        hospital = db.get(Hospital, appt.slot.affiliation.hospital_id)
        if (
            appt.slot.affiliation.hospital_id in hospital_ids_of(db, user)
            and hospital is not None
            and hospital.is_approved
        ):
            return "ADMIN"
    raise errors.not_found("Appointment")
