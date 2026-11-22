"""Request bodies. Responses are plain dicts built in app/serializers.py."""
import re
import uuid
from datetime import date, time
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.constants import ALL_PERMISSIONS, LANGUAGES, SELF_REGISTER_ROLES

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_identifier(value: str) -> tuple[str, str]:
    """Return ("phone" | "email", normalized value). Raises ValueError when neither.

    Phones are Indian mobile numbers stored as 10 digits; a leading +91 or 91 is dropped.
    """
    v = value.strip()
    if "@" in v:
        if _EMAIL.match(v) and len(v) <= 254:
            return "email", v.lower()
        raise ValueError("Enter a valid phone number or email address")
    if re.fullmatch(r"[+0-9\s-]+", v):
        digits = re.sub(r"\D", "", v)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 10:
            return "phone", digits
    raise ValueError("Enter a valid phone number or email address")


def _check_identifier(value: str) -> str:
    normalize_identifier(value)
    return value.strip()


def _check_password(value: str) -> str:
    if len(value) < 8 or len(value) > 128:
        raise ValueError("Password must be 8 to 128 characters")
    if value.isdigit() or value.isalpha():
        raise ValueError("Password must mix letters with numbers or symbols")
    return value


def _check_permissions(values: list[str]) -> list[str]:
    unknown = [v for v in values if v not in ALL_PERMISSIONS]
    if unknown:
        raise ValueError(f"Unknown permissions: {', '.join(unknown)}")
    return sorted(set(values))


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    identifier: str
    password: str
    role: str
    preferred_language: str = "te"

    _v_identifier = field_validator("identifier")(_check_identifier)
    _v_password = field_validator("password")(_check_password)

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in SELF_REGISTER_ROLES:
            raise ValueError("Only patients and caregivers can self-register")
        return v

    @field_validator("preferred_language")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in LANGUAGES:
            raise ValueError("Invalid language selection")
        return v


class LoginIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str
    _v_password = field_validator("new_password")(_check_password)


class ForgotPasswordIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
            raise ValueError("Enter a valid email address")
        return value


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str
    _v_password = field_validator("new_password")(_check_password)


class MeUpdateIn(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    preferred_language: Optional[str] = None
    date_of_birth: Optional[date] = None
    sex: Optional[str] = Field(default=None, max_length=20)
    accessibility_notes: Optional[str] = Field(default=None, max_length=500)

    @field_validator("preferred_language")
    @classmethod
    def _lang(cls, v):
        if v is not None and v not in LANGUAGES:
            raise ValueError("Invalid language selection")
        return v


class CareRequestIn(BaseModel):
    patient_identifier: str
    permissions: list[str] = Field(min_length=1)
    _v_identifier = field_validator("patient_identifier")(_check_identifier)
    _v_permissions = field_validator("permissions")(_check_permissions)


class PermissionsIn(BaseModel):
    permissions: list[str]
    _v_permissions = field_validator("permissions")(_check_permissions)


class RevokeIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


class SuggestIn(BaseModel):
    text: Optional[str] = Field(default=None, max_length=500)
    concern_key: Optional[str] = Field(default=None, max_length=60)


class BookIn(BaseModel):
    slot_id: uuid.UUID
    patient_id: uuid.UUID
    reason_text: Optional[str] = Field(default=None, max_length=500)


class CancelIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


class RescheduleIn(BaseModel):
    new_slot_id: uuid.UUID


class SessionCreateIn(BaseModel):
    language: str = "te"
    patient_id: Optional[uuid.UUID] = None

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in LANGUAGES:
            raise ValueError("Invalid language selection")
        return v


class TurnIn(BaseModel):
    text: Optional[str] = Field(default=None, max_length=500)
    option_value: Optional[str] = Field(default=None, max_length=120)
    input_mode: str = "TEXT"
    stt_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    language: Optional[str] = None

    @field_validator("input_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("TEXT", "VOICE", "BUTTON"):
            raise ValueError("input_mode must be TEXT, VOICE or BUTTON")
        return v


class ConfirmIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class IntakeIn(BaseModel):
    answers: dict[str, str]

    @field_validator("answers")
    @classmethod
    def _answers(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 30:
            raise ValueError("Too many answers")
        return {str(k)[:60]: str(val)[:1000] for k, val in v.items()}


class SummaryPatchIn(BaseModel):
    content: Optional[dict[str, str]] = None
    mark_reviewed: bool = False
    clinician_correction: Optional[str] = Field(default=None, max_length=4000)


class NoteIn(BaseModel):
    note_text: str = Field(min_length=1, max_length=8000)


class FollowUpIn(BaseModel):
    instructions_text: str = Field(min_length=1, max_length=4000)
    next_visit_date: Optional[date] = None


class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class DoctorCreateIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    identifier: str
    password: Optional[str] = None  # required only when the doctor account does not exist yet
    qualifications: str = Field(default="", max_length=200)
    years_experience: Optional[int] = Field(default=None, ge=0, le=70)
    department_id: uuid.UUID
    specialty_id: uuid.UUID
    consultation_fee: Optional[float] = Field(default=None, ge=0, le=100000)
    _v_identifier = field_validator("identifier")(_check_identifier)

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        return _check_password(v) if v else v


class AffiliationPatchIn(BaseModel):
    consultation_fee: Optional[float] = Field(default=None, ge=0, le=100000)
    is_active: Optional[bool] = None


class ScheduleIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    slot_minutes: int = Field(default=20, ge=5, le=120)


class GenerateSlotsIn(BaseModel):
    days: int = Field(default=14, ge=1, le=60)


class WaitlistIn(BaseModel):
    affiliation_id: uuid.UUID
    patient_id: uuid.UUID
