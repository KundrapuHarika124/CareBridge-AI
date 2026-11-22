"""All database tables (25 for the core product, 2 for the waiting list).

Status and role columns are plain strings validated in code (see app/constants.py),
which keeps migrations simple. All timestamps are timezone-aware and stored in UTC.
"""
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float as SqlFloat,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _fk(target: str, **kw) -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey(target), nullable=False, **kw)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    email: Mapped[Optional[str]] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    preferred_language: Mapped[str] = mapped_column(String(5), default="te", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = _created()


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id", unique=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    sex: Mapped[Optional[str]] = mapped_column(String(20))
    accessibility_notes: Mapped[Optional[str]] = mapped_column(String(500))
    user: Mapped["User"] = relationship()


class Doctor(Base):
    __tablename__ = "doctors"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id", unique=True)
    qualifications: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    years_experience: Mapped[Optional[int]] = mapped_column(Integer)
    verification_status: Mapped[str] = mapped_column(String(30), default="SYNTHETIC", nullable=False)
    user: Mapped["User"] = relationship()


class Hospital(Base):
    __tablename__ = "hospitals"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    locality: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    address: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(30), default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Kolkata", nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Real geographical coordinates for location-based discovery
    latitude: Mapped[Optional[float]] = mapped_column(SqlFloat, nullable=True, index=True)
    longitude: Mapped[Optional[float]] = mapped_column(SqlFloat, nullable=True, index=True)
    # Approval status for Super Admin onboarding
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class HospitalStaff(Base):
    __tablename__ = "hospital_staff"
    __table_args__ = (UniqueConstraint("user_id", "hospital_id"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    hospital_id: Mapped[uuid.UUID] = _fk("hospitals.id")


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("hospital_id", "name"),
        UniqueConstraint("id", "hospital_id"),
    )
    id: Mapped[uuid.UUID] = _pk()
    hospital_id: Mapped[uuid.UUID] = _fk("hospitals.id")
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class Specialty(Base):
    __tablename__ = "specialties"
    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(80), nullable=False)
    name_te: Mapped[str] = mapped_column(String(80), nullable=False)


class Affiliation(Base):
    """A doctor at a hospital in a department. Schedules, slots and fees hang off this."""

    __tablename__ = "doctor_hospital_affiliations"
    __table_args__ = (
        UniqueConstraint("doctor_id", "hospital_id", "department_id"),
        UniqueConstraint("id", "doctor_id"),
        ForeignKeyConstraint(
            ("department_id", "hospital_id"),
            ("departments.id", "departments.hospital_id"),
            name="fk_affiliation_department_hospital",
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    doctor_id: Mapped[uuid.UUID] = _fk("doctors.id", index=True)
    hospital_id: Mapped[uuid.UUID] = _fk("hospitals.id", index=True)
    department_id: Mapped[uuid.UUID] = _fk("departments.id")
    specialty_id: Mapped[uuid.UUID] = _fk("specialties.id", index=True)
    consultation_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    doctor: Mapped["Doctor"] = relationship()
    hospital: Mapped["Hospital"] = relationship()
    department: Mapped["Department"] = relationship(foreign_keys="[Affiliation.department_id]")
    specialty: Mapped["Specialty"] = relationship()


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"
    id: Mapped[uuid.UUID] = _pk()
    affiliation_id: Mapped[uuid.UUID] = _fk("doctor_hospital_affiliations.id", index=True)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = Monday
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_minutes: Mapped[int] = mapped_column(Integer, default=20, nullable=False)


class AppointmentSlot(Base):
    __tablename__ = "appointment_slots"
    __table_args__ = (
        UniqueConstraint("affiliation_id", "starts_at"),
        # A doctor cannot have two slots starting at the same moment at different hospitals.
        UniqueConstraint("doctor_id", "starts_at"),
        Index("ix_slots_available", "affiliation_id", "starts_at", postgresql_where=text("status = 'AVAILABLE'")),
        ForeignKeyConstraint(
            ("affiliation_id", "doctor_id"),
            ("doctor_hospital_affiliations.id", "doctor_hospital_affiliations.doctor_id"),
            name="fk_slot_affiliation_doctor",
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    affiliation_id: Mapped[uuid.UUID] = _fk("doctor_hospital_affiliations.id")
    doctor_id: Mapped[uuid.UUID] = _fk("doctors.id")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="AVAILABLE", nullable=False)
    affiliation: Mapped["Affiliation"] = relationship(foreign_keys="[AppointmentSlot.affiliation_id]")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # Second line of defence against double booking: one active appointment per slot.
        Index(
            "uq_active_appointment_per_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'CONFIRMED')"),
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    slot_id: Mapped[uuid.UUID] = _fk("appointment_slots.id", index=True)
    patient_id: Mapped[uuid.UUID] = _fk("patients.id", index=True)
    booked_by_user_id: Mapped[uuid.UUID] = _fk("users.id")
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    reason_text: Mapped[Optional[str]] = mapped_column(String(500))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    rescheduled_from_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, ForeignKey("appointments.id"))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(300))
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    slot: Mapped["AppointmentSlot"] = relationship()
    patient: Mapped["Patient"] = relationship()


class CareRelationship(Base):
    __tablename__ = "care_relationships"
    __table_args__ = (
        Index(
            "uq_open_care_relationship",
            "caregiver_user_id",
            "patient_id",
            unique=True,
            postgresql_where=text("status IN ('REQUESTED', 'ACTIVE')"),
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    caregiver_user_id: Mapped[uuid.UUID] = _fk("users.id", index=True)
    patient_id: Mapped[uuid.UUID] = _fk("patients.id", index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    requested_permissions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    requested_at: Mapped[datetime] = _created()
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(300))
    patient: Mapped["Patient"] = relationship()
    caregiver: Mapped["User"] = relationship()


class CaregiverPermission(Base):
    __tablename__ = "caregiver_permissions"
    relationship_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("care_relationships.id"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(40), primary_key=True)
    granted_at: Mapped[datetime] = _created()


class ConsentRecord(Base):
    """Append-only history of consent decisions. Never updated or deleted by the application."""

    __tablename__ = "consent_records"
    id: Mapped[uuid.UUID] = _pk()
    relationship_id: Mapped[uuid.UUID] = _fk("care_relationships.id", index=True)
    actor_user_id: Mapped[uuid.UUID] = _fk("users.id")
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # REQUESTED GRANTED MODIFIED REJECTED REVOKED
    permissions_snapshot: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    consent_text_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = _created()


class SpecialtyMapping(Base):
    __tablename__ = "specialty_mappings"
    id: Mapped[uuid.UUID] = _pk()
    specialty_id: Mapped[uuid.UUID] = _fk("specialties.id")
    concern_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    label_en: Mapped[str] = mapped_column(String(120), nullable=False)
    label_te: Mapped[str] = mapped_column(String(120), nullable=False)
    phrases: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    explanation_en: Mapped[str] = mapped_column(String(300), nullable=False)
    explanation_te: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), default="DEMO_UNREVIEWED", nullable=False)
    source: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    specialty: Mapped["Specialty"] = relationship()


class Questionnaire(Base):
    __tablename__ = "questionnaires"
    id: Mapped[uuid.UUID] = _pk()
    specialty_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, ForeignKey("specialties.id"))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    title_en: Mapped[str] = mapped_column(String(160), nullable=False)
    title_te: Mapped[str] = mapped_column(String(160), nullable=False)
    questions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), default="DEMO_UNREVIEWED", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class QuestionnaireResponse(Base):
    __tablename__ = "questionnaire_responses"
    id: Mapped[uuid.UUID] = _pk()
    appointment_id: Mapped[uuid.UUID] = _fk("appointments.id", unique=True)
    questionnaire_id: Mapped[uuid.UUID] = _fk("questionnaires.id")
    answers: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    submitted_by_user_id: Mapped[uuid.UUID] = _fk("users.id")
    submitted_at: Mapped[datetime] = _created()


class ConsultationSummary(Base):
    """AI-generated summary. Kept apart from clinician-authored tables on purpose."""

    __tablename__ = "consultation_summaries"
    id: Mapped[uuid.UUID] = _pk()
    appointment_id: Mapped[uuid.UUID] = _fk("appointments.id", unique=True)
    content: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(10), default="AI", nullable=False)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = _created()
    patient_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    patient_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    clinician_correction: Mapped[Optional[str]] = mapped_column(Text)


class ConsultationNote(Base):
    __tablename__ = "consultation_notes"
    id: Mapped[uuid.UUID] = _pk()
    appointment_id: Mapped[uuid.UUID] = _fk("appointments.id", unique=True)
    doctor_id: Mapped[uuid.UUID] = _fk("doctors.id")
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _created()


class FollowUpInstruction(Base):
    __tablename__ = "follow_up_instructions"
    id: Mapped[uuid.UUID] = _pk()
    appointment_id: Mapped[uuid.UUID] = _fk("appointments.id", unique=True)
    doctor_id: Mapped[uuid.UUID] = _fk("doctors.id")
    instructions_text: Mapped[str] = mapped_column(Text, nullable=False)
    next_visit_date: Mapped[Optional[date]] = mapped_column(Date)
    updated_at: Mapped[datetime] = _created()


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id", index=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    channel: Mapped[str] = mapped_column(String(10), default="IN_APP", nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="SENT", nullable=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    """Append-only. Holds identifiers and action names, never clinical text or secrets."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),)
    id: Mapped[uuid.UUID] = _pk()
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, ForeignKey("users.id"))
    hospital_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, ForeignKey("hospitals.id"), index=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(40))
    request_id: Mapped[Optional[str]] = mapped_column(String(40))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created()


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id", index=True)
    patient_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, ForeignKey("patients.id"))
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # collected fields and pending options
    turn_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (UniqueConstraint("session_id", "seq"),)
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = _fk("conversation_sessions.id", index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # USER | ASSISTANT
    input_mode: Mapped[Optional[str]] = mapped_column(String(10))  # VOICE | TEXT | BUTTON
    body: Mapped[str] = mapped_column(Text, nullable=False)
    stt_confidence: Mapped[Optional[float]] = mapped_column(SqlFloat)
    created_at: Mapped[datetime] = _created()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id", index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id", index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class WaitingListEntry(Base):
    __tablename__ = "waiting_list_entries"
    __table_args__ = (
        Index(
            "uq_open_waiting_entry",
            "patient_id",
            "affiliation_id",
            unique=True,
            postgresql_where=text("status IN ('ACTIVE', 'OFFERED')"),
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = _fk("patients.id", index=True)
    affiliation_id: Mapped[uuid.UUID] = _fk("doctor_hospital_affiliations.id", index=True)
    created_by_user_id: Mapped[uuid.UUID] = _fk("users.id")
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = _created()
    affiliation: Mapped["Affiliation"] = relationship()
    patient: Mapped["Patient"] = relationship()


class WaitingListOffer(Base):
    __tablename__ = "waiting_list_offers"
    __table_args__ = (
        Index("uq_open_offer_per_slot", "slot_id", unique=True, postgresql_where=text("status = 'OPEN'")),
    )
    id: Mapped[uuid.UUID] = _pk()
    entry_id: Mapped[uuid.UUID] = _fk("waiting_list_entries.id", index=True)
    slot_id: Mapped[uuid.UUID] = _fk("appointment_slots.id")
    status: Mapped[str] = mapped_column(String(10), default="OPEN", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    entry: Mapped["WaitingListEntry"] = relationship()
    slot: Mapped["AppointmentSlot"] = relationship()
