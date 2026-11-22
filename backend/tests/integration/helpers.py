"""Shared builders for integration tests."""
from datetime import timedelta
from decimal import Decimal

from app.constants import ROLE_DOCTOR, ROLE_HOSPITAL_ADMIN, SLOT_AVAILABLE
from app.core.security import hash_password
from app.core.timeutil import utcnow
from app.models import (
    Affiliation,
    AppointmentSlot,
    Department,
    Doctor,
    Hospital,
    HospitalStaff,
    Questionnaire,
    Specialty,
    SpecialtyMapping,
    User,
)

PASSWORD = "Test@12345"
API = "/api/v1"


def make_slot(db, aff, hours_ahead: float, status: str = SLOT_AVAILABLE) -> AppointmentSlot:
    start = (utcnow() + timedelta(hours=hours_ahead)).replace(second=0, microsecond=0)
    slot = AppointmentSlot(affiliation_id=aff.id, doctor_id=aff.doctor_id, starts_at=start,
                           ends_at=start + timedelta(minutes=20), status=status)
    db.add(slot)
    db.commit()
    return slot


def build_world(db) -> dict:
    """Two hospitals, one doctor each, an admin each, and a few future slots."""
    pw = hash_password(PASSWORD)
    ortho = Specialty(code="ORTHOPAEDICS", name_en="Orthopaedics", name_te="ఎముకల వైద్యం")
    general = Specialty(code="GENERAL_MEDICINE", name_en="General Medicine", name_te="సాధారణ వైద్యం")
    db.add_all([ortho, general])
    db.flush()
    db.add(SpecialtyMapping(specialty_id=ortho.id, concern_key="joint_pain", label_en="Joint pain", label_te="కీళ్ల నొప్పి",
                            phrases=["knee pain", "మోకాలి నొప్పి", "mokali noppi"], explanation_en="Bones and joints.",
                            explanation_te="ఎముకలు, కీళ్లు."))
    db.add(Questionnaire(specialty_id=None, version=1, title_en="Before your visit", title_te="సందర్శనకు ముందు",
                         questions=[{"key": "main_concern", "text_en": "Main reason?", "text_te": "ప్రధాన కారణం?"},
                                    {"key": "duration", "text_en": "How long?", "text_te": "ఎంతకాలం?"}]))
    out = {"specialty_ortho": ortho, "specialty_general": general}
    for n, locality in ((1, "Kukatpally"), (2, "Banjara Hills")):
        hospital = Hospital(
            name=f"Simulated Hospital {n}",
            locality=locality,
            city="Hyderabad",
            is_approved=True,
            approved_at=utcnow(),
        )
        db.add(hospital)
        db.flush()
        dept = Department(hospital_id=hospital.id, name="Orthopaedics")
        admin = User(full_name=f"Admin {n}", email=f"admin{n}@test.demo", role=ROLE_HOSPITAL_ADMIN, password_hash=pw)
        doc_user = User(full_name=f"Dr. Test {n}", email=f"doctor{n}@test.demo", role=ROLE_DOCTOR, password_hash=pw)
        db.add_all([dept, admin, doc_user])
        db.flush()
        db.add(HospitalStaff(user_id=admin.id, hospital_id=hospital.id))
        doctor = Doctor(user_id=doc_user.id, qualifications="MBBS, MS")
        db.add(doctor)
        db.flush()
        aff = Affiliation(doctor_id=doctor.id, hospital_id=hospital.id, department_id=dept.id, specialty_id=ortho.id,
                          consultation_fee=Decimal("500"))
        db.add(aff)
        db.commit()
        slots = [make_slot(db, aff, 24 * n + i) for i in range(1, 5)]
        out[f"h{n}"] = {"hospital": hospital, "dept": dept, "admin": admin, "doctor_user": doc_user, "doctor": doctor,
                        "aff": aff, "slots": slots}
    return out


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register(client, name: str, identifier: str, role: str = "PATIENT", language: str = "en") -> dict:
    r = client.post(f"{API}/auth/register", json={"full_name": name, "identifier": identifier, "password": PASSWORD,
                                                  "role": role, "preferred_language": language})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    return {"headers": auth(data["access_token"]), "user": data["user"], "patient_id": data["user"]["patient_id"]}


def login(client, identifier: str, password: str = PASSWORD) -> dict:
    r = client.post(f"{API}/auth/login", json={"identifier": identifier, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    return {"headers": auth(data["access_token"]), "user": data["user"]}


def book(client, who: dict, slot, patient_id=None, key: str | None = None):
    headers = dict(who["headers"])
    if key:
        headers["Idempotency-Key"] = key
    return client.post(f"{API}/appointments", headers=headers,
                       json={"slot_id": str(slot.id), "patient_id": str(patient_id or who["patient_id"])})


def grant(client, caregiver: dict, patient: dict, patient_identifier: str, permissions: list[str]) -> str:
    """Caregiver requests access, patient approves `permissions`. Returns the relationship id."""
    r = client.post(f"{API}/care/requests", headers=caregiver["headers"],
                    json={"patient_identifier": patient_identifier, "permissions": permissions})
    assert r.status_code == 202, r.text
    rels = client.get(f"{API}/care/relationships", headers=patient["headers"]).json()["data"]
    rel_id = next(r["id"] for r in rels if r["status"] == "REQUESTED")
    r = client.post(f"{API}/care/relationships/{rel_id}/approve", headers=patient["headers"],
                    json={"permissions": permissions})
    assert r.status_code == 200, r.text
    return rel_id
