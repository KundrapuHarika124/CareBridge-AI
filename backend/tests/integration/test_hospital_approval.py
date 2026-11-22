import uuid
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

from app.constants import ROLE_SUPER_ADMIN
from app.core.timeutil import utcnow
from app.core.security import hash_password
from app.constants import ROLE_DOCTOR, SLOT_AVAILABLE, SLOT_HELD, WAIT_ACTIVE, WAIT_OFFERED, OFFER_OPEN
from app.models import (
    Affiliation,
    Appointment,
    AppointmentSlot,
    Department,
    Doctor,
    Hospital,
    User,
    WaitingListEntry,
    WaitingListOffer,
)
from app.core import errors
from app.core.database import SessionLocal
from app.models import Patient
from tests.integration.helpers import API, PASSWORD, login, register


def create_unapproved_affiliation(db, world, name, *, is_approved=False):
    hospital = Hospital(
        name=name,
        locality="Test Locality",
        city="Hyderabad",
        is_simulated=False,
        is_approved=is_approved,
        approved_at=utcnow() if is_approved else None,
    )
    db.add(hospital)
    db.flush()
    department = Department(hospital_id=hospital.id, name="General Medicine")
    doctor_user = User(
        full_name=f"Dr. {name}",
        email=f"{name.lower().replace(' ', '-')}@test.demo",
        password_hash=hash_password(PASSWORD),
        role=ROLE_DOCTOR,
        preferred_language="en",
    )
    db.add_all([department, doctor_user])
    db.flush()
    doctor = Doctor(user_id=doctor_user.id, qualifications="MBBS")
    db.add(doctor)
    db.flush()
    affiliation = Affiliation(
        doctor_id=doctor.id,
        hospital_id=hospital.id,
        department_id=department.id,
        specialty_id=world["specialty_ortho"].id,
        is_active=True,
    )
    db.add(affiliation)
    db.flush()
    return hospital, affiliation


def create_slot(db, affiliation, *, status=SLOT_AVAILABLE):
    start = (utcnow() + timedelta(hours=200)).replace(second=0, microsecond=0)
    slot = AppointmentSlot(
        affiliation_id=affiliation.id,
        doctor_id=affiliation.doctor_id,
        starts_at=start,
        ends_at=start + timedelta(minutes=20),
        status=status,
    )
    db.add(slot)
    db.flush()
    return slot


def test_pending_hospital_is_hidden_and_admin_cannot_bypass_approval(client, db):
    super_user = User(
        full_name="Test Super Admin",
        email="super@test.demo",
        password_hash=hash_password(PASSWORD),
        role=ROLE_SUPER_ADMIN,
        preferred_language="en",
        is_active=True,
    )
    db.add(super_user)
    db.commit()
    super_auth = login(client, "super@test.demo")
    assert super_auth["user"]["role"] == ROLE_SUPER_ADMIN

    created = client.post(
        f"{API}/admin/hospitals",
        headers=super_auth["headers"],
        json={
            "name": "Pending Hospital",
            "locality": "Test Locality",
            "city": "Hyderabad",
            "address": "Test Address",
            "phone": "0000000000",
            "latitude": 17.385,
            "longitude": 78.4867,
            "admin_name": "Pending Hospital Admin",
            "admin_email": "pending-admin@test.demo",
            "admin_password": PASSWORD,
        },
    )
    assert created.status_code == 201, created.text
    hospital = created.json()["data"]["hospital"]
    hospital_id = hospital["id"]
    assert hospital["is_approved"] is False

    pending = client.get(
        f"{API}/admin/hospitals/pending",
        headers=super_auth["headers"],
    )
    assert pending.status_code == 200
    assert hospital_id in [row["id"] for row in pending.json()["data"]]

    patient = register(client, "Patient", "patient@test.demo")
    public_hospitals = client.get(
        f"{API}/hospitals",
        headers=patient["headers"],
    )
    assert public_hospitals.status_code == 200
    assert hospital_id not in [row["id"] for row in public_hospitals.json()["data"]]

    nearby = client.get(
        f"{API}/hospitals/nearby",
        headers=patient["headers"],
        params={"latitude": 17.385, "longitude": 78.4867, "max_distance_km": 50},
    )
    assert nearby.status_code == 200
    assert hospital_id not in [row["id"] for row in nearby.json()["data"]]

    # Pending hospital admin must not log in.
    pending_login = client.post(
        f"{API}/auth/login",
        json={
            "identifier": "pending-admin@test.demo",
            "password": PASSWORD,
        },
    )
    assert pending_login.status_code == 401

    # Log in while approved, then revoke approval to test existing sessions.
    hospital_record = db.get(Hospital, uuid.UUID(hospital_id))
    hospital_record.is_approved = True
    hospital_record.approved_at = utcnow()
    db.commit()

    admin_auth = login(client, "pending-admin@test.demo")

    hospital_record.is_approved = False
    hospital_record.approved_at = None
    db.commit()

    # Previously issued access token must now be rejected.
    overview = client.get(
        f"{API}/admin/hospitals/{hospital_id}/overview",
        headers=admin_auth["headers"],
    )
    assert overview.status_code == 403

    # Previously issued refresh token must also be rejected.
    refresh = client.post(
        f"{API}/auth/refresh",
        headers={"X-Requested-With": "carebridge"},
    )
    assert refresh.status_code == 401

    patient_patch = client.patch(
        f"{API}/admin/hospitals/{hospital_id}",
        headers=patient["headers"],
        json={"is_approved": True},
    )
    assert patient_patch.status_code == 403



def test_superadmin_approval_and_rejection_update_discovery(client, db):
    super_user = User(
        full_name="Test Super Admin",
        email="super2@test.demo",
        password_hash=hash_password(PASSWORD),
        role=ROLE_SUPER_ADMIN,
        preferred_language="en",
        is_active=True,
    )
    db.add(super_user)
    db.commit()
    super_auth = login(client, "super2@test.demo")
    assert super_auth["user"]["role"] == ROLE_SUPER_ADMIN

    created = client.post(
        f"{API}/admin/hospitals",
        headers=super_auth["headers"],
        json={
            "name": "Approval Lifecycle Hospital",
            "locality": "Lifecycle Locality",
            "city": "Hyderabad",
            "address": "Lifecycle Address",
            "phone": "1111111111",
            "latitude": 17.4,
            "longitude": 78.5,
            "admin_name": "Lifecycle Hospital Admin",
            "admin_email": "lifecycle-admin@test.demo",
            "admin_password": PASSWORD,
        },
    )
    assert created.status_code == 201, created.text
    hospital = created.json()["data"]["hospital"]
    hospital_id = hospital["id"]

    approved = client.patch(
        f"{API}/admin/hospitals/{hospital_id}",
        headers=super_auth["headers"],
        json={"is_approved": True, "note": "Approved for testing"},
    )
    assert approved.status_code == 200, approved.text
    approved_hospital = approved.json()["data"]
    assert approved_hospital["is_approved"] is True
    db.expire_all()
    hospital_row = db.get(Hospital, uuid.UUID(hospital_id))
    assert hospital_row.approved_at is not None

    patient = register(client, "Patient", "patient2@test.demo")
    public_hospitals = client.get(
        f"{API}/hospitals",
        headers=patient["headers"],
    )
    assert hospital_id in [row["id"] for row in public_hospitals.json()["data"]]

    nearby = client.get(
        f"{API}/hospitals/nearby",
        headers=patient["headers"],
        params={"latitude": 17.4, "longitude": 78.5, "max_distance_km": 50},
    )
    assert nearby.status_code == 200
    assert hospital_id in [row["id"] for row in nearby.json()["data"]]

    admin_auth = login(client, "lifecycle-admin@test.demo")
    overview = client.get(
        f"{API}/admin/hospitals/{hospital_id}/overview",
        headers=admin_auth["headers"],
    )
    assert overview.status_code == 200

    rejected = client.patch(
        f"{API}/admin/hospitals/{hospital_id}",
        headers=super_auth["headers"],
        json={"is_approved": False, "note": "Rejected for testing"},
    )
    assert rejected.status_code == 200, rejected.text
    rejected_hospital = rejected.json()["data"]
    assert rejected_hospital["is_approved"] is False
    db.expire_all()
    hospital_row = db.get(Hospital, uuid.UUID(hospital_id))
    assert hospital_row.approved_at is None

    public_after_rejection = client.get(
        f"{API}/hospitals",
        headers=patient["headers"],
    )
    assert hospital_id not in [row["id"] for row in public_after_rejection.json()["data"]]

    overview_after_rejection = client.get(
        f"{API}/admin/hospitals/{hospital_id}/overview",
        headers=admin_auth["headers"],
    )
    assert overview_after_rejection.status_code == 403


def test_rejection_cleans_open_offer_entry_and_held_slot(client, db, world):
    super_user = User(
        full_name="Cleanup Super Admin",
        email="cleanup-super@test.demo",
        password_hash=hash_password(PASSWORD),
        role=ROLE_SUPER_ADMIN,
        preferred_language="en",
        is_active=True,
    )
    db.add(super_user)
    db.commit()
    super_auth = login(client, "cleanup-super@test.demo")
    hospital = world["h1"]["hospital"]
    affiliation = world["h1"]["aff"]
    slot = create_slot(db, affiliation, status=SLOT_HELD)
    patient = register(client, "Cleanup Patient", "cleanup-patient@test.demo")
    patient_row = db.get(Patient, uuid.UUID(patient["patient_id"]))
    entry = WaitingListEntry(
        patient_id=patient_row.id,
        affiliation_id=affiliation.id,
        created_by_user_id=patient_row.user_id,
        status=WAIT_OFFERED,
    )
    db.add(entry)
    db.flush()
    offer = WaitingListOffer(
        entry_id=entry.id,
        slot_id=slot.id,
        status=OFFER_OPEN,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.add(offer)
    db.commit()

    response = client.patch(
        f"{API}/admin/hospitals/{hospital.id}",
        headers=super_auth["headers"],
        json={"is_approved": False, "note": "Reject with waiting state"},
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(WaitingListOffer, offer.id).status == "EXPIRED"
    assert db.get(WaitingListEntry, entry.id).status == "CANCELLED"
    assert db.get(AppointmentSlot, slot.id).status == "AVAILABLE"


def test_rejection_does_not_release_booked_slot_and_preserves_other_hospital(client, db, world):
    super_user = User(
        full_name="Isolation Super Admin",
        email="isolation-super@test.demo",
        password_hash=hash_password(PASSWORD),
        role=ROLE_SUPER_ADMIN,
        preferred_language="en",
        is_active=True,
    )
    db.add(super_user)
    db.commit()
    super_auth = login(client, "isolation-super@test.demo")

    h1 = world["h1"]
    h2 = world["h2"]
    booked_slot = create_slot(db, h1["aff"], status="BOOKED")
    other_slot = create_slot(db, h2["aff"], status=SLOT_HELD)
    patient = register(client, "Isolation Patient", "isolation-patient@test.demo")
    patient_row = db.get(Patient, uuid.UUID(patient["patient_id"]))
    h1_entry = WaitingListEntry(
        patient_id=patient_row.id,
        affiliation_id=h1["aff"].id,
        created_by_user_id=patient_row.user_id,
        status=WAIT_OFFERED,
    )
    h2_entry = WaitingListEntry(
        patient_id=patient_row.id,
        affiliation_id=h2["aff"].id,
        created_by_user_id=patient_row.user_id,
        status=WAIT_OFFERED,
    )
    db.add_all([h1_entry, h2_entry])
    db.flush()
    h1_offer = WaitingListOffer(
        entry_id=h1_entry.id,
        slot_id=booked_slot.id,
        status=OFFER_OPEN,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    h2_offer = WaitingListOffer(
        entry_id=h2_entry.id,
        slot_id=other_slot.id,
        status=OFFER_OPEN,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.add_all([h1_offer, h2_offer])
    db.commit()

    response = client.patch(
        f"{API}/admin/hospitals/{h1['hospital'].id}",
        headers=super_auth["headers"],
        json={"is_approved": False, "note": "Reject one hospital"},
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(WaitingListOffer, h1_offer.id).status == "EXPIRED"
    assert db.get(AppointmentSlot, booked_slot.id).status == "BOOKED"
    assert db.get(WaitingListOffer, h2_offer.id).status == "OPEN"
    assert db.get(AppointmentSlot, other_slot.id).status == "HELD"
    assert db.get(WaitingListEntry, h2_entry.id).status == "OFFERED"


def test_repeated_cleanup_is_idempotent(client, db, world):
    from app.services import waitlist

    hospital = world["h1"]["hospital"]
    affiliation = world["h1"]["aff"]
    slot = create_slot(db, affiliation, status=SLOT_HELD)
    patient = register(client, "Repeated Cleanup Patient", "repeated-cleanup@test.demo")
    patient_row = db.get(Patient, uuid.UUID(patient["patient_id"]))
    entry = WaitingListEntry(
        patient_id=patient_row.id,
        affiliation_id=affiliation.id,
        created_by_user_id=patient_row.user_id,
        status=WAIT_OFFERED,
    )
    db.add(entry)
    db.flush()
    offer = WaitingListOffer(
        entry_id=entry.id,
        slot_id=slot.id,
        status=OFFER_OPEN,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.add(offer)
    db.commit()
    hospital.is_approved = False
    db.commit()

    first = waitlist.cleanup_rejected_hospital(db, hospital.id)
    db.commit()
    second = waitlist.cleanup_rejected_hospital(db, hospital.id)
    db.commit()
    assert first["offers"] == 1
    assert first["entries"] == 1
    assert first["slots"] == 1
    assert second == {"offers": 0, "entries": 0, "slots": 0}


def test_cleanup_failure_rolls_back_hospital_rejection(client, db, world, monkeypatch):
    super_user = User(
        full_name="Rollback Super Admin",
        email="rollback-super@test.demo",
        password_hash=hash_password(PASSWORD),
        role=ROLE_SUPER_ADMIN,
        preferred_language="en",
        is_active=True,
    )
    db.add(super_user)
    db.commit()
    super_auth = login(client, "rollback-super@test.demo")
    hospital = world["h1"]["hospital"]

    from app.services import waitlist

    def fail_cleanup(*args, **kwargs):
        raise RuntimeError("cleanup failure")

    monkeypatch.setattr(waitlist, "cleanup_rejected_hospital", fail_cleanup)
    response = client.patch(
        f"{API}/admin/hospitals/{hospital.id}",
        headers=super_auth["headers"],
        json={"is_approved": False, "note": "Must roll back"},
    )
    assert response.status_code == 500
    db.expire_all()
    assert db.get(Hospital, hospital.id).is_approved is True


def test_booking_pending_hospital_slot_is_rejected(client, db, world):
    patient = register(client, "Pending Patient", "pending-patient@test.demo")
    _, affiliation = create_unapproved_affiliation(db, world, "Pending Booking Hospital")
    slot = create_slot(db, affiliation)

    response = client.post(
        f"{API}/appointments",
        headers=patient["headers"],
        json={"slot_id": str(slot.id), "patient_id": patient["patient_id"]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_booking_rejected_hospital_slot_is_rejected(client, db, world):
    patient = register(client, "Rejected Patient", "rejected-patient@test.demo")
    _, affiliation = create_unapproved_affiliation(db, world, "Rejected Booking Hospital")
    slot = create_slot(db, affiliation)

    response = client.post(
        f"{API}/appointments",
        headers=patient["headers"],
        json={"slot_id": str(slot.id), "patient_id": patient["patient_id"]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_join_waiting_list_for_unapproved_hospital_is_rejected(client, db, world):
    patient = register(client, "Waiting Patient", "waiting-patient@test.demo")
    _, affiliation = create_unapproved_affiliation(db, world, "Pending Waiting Hospital")

    response = client.post(
        f"{API}/waiting-list",
        headers=patient["headers"],
        json={"affiliation_id": str(affiliation.id), "patient_id": patient["patient_id"]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_accept_offer_for_unapproved_hospital_cannot_create_appointment(client, db, world):
    patient = register(client, "Offer Patient", "offer-patient@test.demo")
    _, affiliation = create_unapproved_affiliation(db, world, "Pending Offer Hospital")
    slot = create_slot(db, affiliation, status=SLOT_HELD)

    from app.models import Patient

    patient_row = db.get(Patient, uuid.UUID(patient["patient_id"]))
    entry = WaitingListEntry(
        patient_id=patient_row.id,
        affiliation_id=affiliation.id,
        created_by_user_id=patient_row.user_id,
        status=WAIT_OFFERED,
    )
    db.add(entry)
    db.flush()
    offer = WaitingListOffer(
        entry_id=entry.id,
        slot_id=slot.id,
        status=OFFER_OPEN,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.add(offer)
    db.commit()

    response = client.post(
        f"{API}/waiting-list/offers/{offer.id}/accept",
        headers=patient["headers"],
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_booking_hospital_lock_prevents_concurrent_rejection_until_commit(client, db, world, monkeypatch):
    super_user = User(
        full_name="Concurrent Super Admin",
        email="concurrent-super@test.demo",
        password_hash=hash_password(PASSWORD),
        role=ROLE_SUPER_ADMIN,
        preferred_language="en",
        is_active=True,
    )
    db.add(super_user)
    db.commit()
    super_auth = login(client, "concurrent-super@test.demo")

    patient = register(client, "Concurrent Patient", "concurrent-patient@test.demo")
    slot = world["h1"]["slots"][0]

    from app.services import booking

    booking_checked = Event()
    allow_booking_commit = Event()
    original_patient_busy = booking._patient_busy

    def pause_after_hospital_lock(session, patient_id, checked_slot, ignore=None):
        booking_checked.set()
        if not allow_booking_commit.wait(timeout=5):
            raise RuntimeError("Timed out waiting for booking commit")
        return original_patient_busy(session, patient_id, checked_slot, ignore)

    monkeypatch.setattr(booking, "_patient_busy", pause_after_hospital_lock)

    def run_booking():
        session = SessionLocal()
        try:
            patient_row = session.get(Patient, uuid.UUID(patient["patient_id"]))
            actor = session.get(User, patient_row.user_id)
            try:
                appt = booking.book(
                    session,
                    actor=actor,
                    patient=patient_row,
                    slot_id=slot.id,
                )
                return ("ok", appt.status)
            except errors.AppError as exc:
                return ("error", exc.code)
        finally:
            session.close()

    def run_rejection():
        return client.patch(
            f"{API}/admin/hospitals/{world['h1']['hospital'].id}",
            headers=super_auth["headers"],
            json={"is_approved": False, "note": "Concurrent rejection"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        booking_future = pool.submit(run_booking)
        assert booking_checked.wait(timeout=5)
        rejection_future = pool.submit(run_rejection)
        time.sleep(0.2)
        assert not rejection_future.done()
        allow_booking_commit.set()
        booking_result = booking_future.result(timeout=5)
        rejection_response = rejection_future.result(timeout=5)

    assert booking_result == ("ok", "CONFIRMED")
    assert rejection_response.status_code == 200

    db.expire_all()
    assert db.get(Hospital, world["h1"]["hospital"].id).is_approved is False
    assert db.get(AppointmentSlot, slot.id).status == "BOOKED"


def test_rejection_hospital_lock_first_rejects_subsequent_booking(client, db, world, monkeypatch):
    super_user = User(
        full_name="Concurrent Rejection Super Admin",
        email="concurrent-rejection-super@test.demo",
        password_hash=hash_password(PASSWORD),
        role=ROLE_SUPER_ADMIN,
        preferred_language="en",
        is_active=True,
    )
    db.add(super_user)
    db.commit()
    super_auth = login(client, "concurrent-rejection-super@test.demo")

    patient = register(client, "Rejected Concurrent Patient", "rejected-concurrent-patient@test.demo")
    slot = world["h1"]["slots"][0]

    from app.api import superadmin

    rejection_locked = Event()
    allow_rejection_commit = Event()
    original_audit_db = superadmin.audit_db

    def pause_after_hospital_lock(*args, **kwargs):
        rejection_locked.set()
        if not allow_rejection_commit.wait(timeout=5):
            raise RuntimeError("Timed out waiting for rejection commit")
        return original_audit_db(*args, **kwargs)

    monkeypatch.setattr(superadmin, "audit_db", pause_after_hospital_lock)

    def run_rejection():
        return client.patch(
            f"{API}/admin/hospitals/{world['h1']['hospital'].id}",
            headers=super_auth["headers"],
            json={"is_approved": False, "note": "Reject first"},
        )

    def run_booking():
        from app.services import booking

        session = SessionLocal()
        try:
            patient_row = session.get(Patient, uuid.UUID(patient["patient_id"]))
            actor = session.get(User, patient_row.user_id)
            try:
                booking.book(
                    session,
                    actor=actor,
                    patient=patient_row,
                    slot_id=slot.id,
                )
                return ("ok", None)
            except errors.AppError as exc:
                return ("error", exc.code)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        rejection_future = pool.submit(run_rejection)
        assert rejection_locked.wait(timeout=5)
        booking_future = pool.submit(run_booking)
        time.sleep(0.2)
        assert not booking_future.done()
        allow_rejection_commit.set()
        rejection_response = rejection_future.result(timeout=5)
        booking_result = booking_future.result(timeout=5)

    assert rejection_response.status_code == 200
    assert booking_result == ("error", "NOT_FOUND")

    db.expire_all()
    assert db.get(Hospital, world["h1"]["hospital"].id).is_approved is False
    assert db.get(AppointmentSlot, slot.id).status == "AVAILABLE"


def test_direct_booking_waits_for_waiting_acceptance_hospital_and_slot_locks(client, db, world, monkeypatch):
    holder = register(client, "Holder", "race-holder@test.demo")
    waiting = register(client, "Waiting", "race-waiting@test.demo")
    direct = register(client, "Direct", "race-direct@test.demo")
    slot = world["h1"]["slots"][0]
    aff = world["h1"]["aff"]

    holder_appt = client.post(
        f"{API}/appointments",
        headers=holder["headers"],
        json={"slot_id": str(slot.id), "patient_id": holder["patient_id"]},
    )
    assert holder_appt.status_code == 201
    join = client.post(
        f"{API}/waiting-list",
        headers=waiting["headers"],
        json={"affiliation_id": str(aff.id), "patient_id": waiting["patient_id"]},
    )
    assert join.status_code == 201
    cancel = client.post(
        f"{API}/appointments/{holder_appt.json()['data']['id']}/cancel",
        headers=holder["headers"],
        json={},
    )
    assert cancel.status_code == 200
    waiting_list = client.get(
        f"{API}/waiting-list?patient_id={waiting['patient_id']}",
        headers=waiting["headers"],
    ).json()["data"]
    assert len(waiting_list["offers"]) == 1
    offer_id = waiting_list["offers"][0]["id"]

    from app.services import booking

    acceptance_locked = Event()
    allow_acceptance_commit = Event()
    original_patient_busy = booking._patient_busy

    def pause_acceptance(session, patient_id, checked_slot, ignore=None):
        acceptance_locked.set()
        if not allow_acceptance_commit.wait(timeout=5):
            raise RuntimeError("Timed out waiting for acceptance commit")
        return original_patient_busy(session, patient_id, checked_slot, ignore)

    monkeypatch.setattr(booking, "_patient_busy", pause_acceptance)

    def run_acceptance():
        return client.post(
            f"{API}/waiting-list/offers/{offer_id}/accept",
            headers=waiting["headers"],
        )

    def run_direct_booking():
        session = SessionLocal()
        try:
            patient_row = session.get(Patient, uuid.UUID(direct["patient_id"]))
            actor = session.get(User, patient_row.user_id)
            try:
                booking.book(
                    session,
                    actor=actor,
                    patient=patient_row,
                    slot_id=slot.id,
                )
                return ("ok", None)
            except errors.AppError as exc:
                return ("error", exc.code)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        acceptance_future = pool.submit(run_acceptance)
        assert acceptance_locked.wait(timeout=5)
        direct_future = pool.submit(run_direct_booking)
        direct_future_running = not direct_future.done()
        allow_acceptance_commit.set()
        acceptance_response = acceptance_future.result(timeout=5)
        direct_result = direct_future.result(timeout=5)

    assert direct_future_running
    assert acceptance_response.status_code == 201
    assert direct_result == ("error", "SLOT_UNAVAILABLE")


def test_reschedule_waits_for_waiting_acceptance_hospital_and_slot_locks(client, db, world, monkeypatch):
    patient = register(client, "Reschedule Patient", "race-reschedule@test.demo")
    waiting = register(client, "Reschedule Waiting", "race-reschedule-waiting@test.demo")
    old_slot = world["h1"]["slots"][0]
    new_slot = world["h1"]["slots"][1]
    offer_slot = world["h1"]["slots"][2]

    old_appt = client.post(
        f"{API}/appointments",
        headers=patient["headers"],
        json={"slot_id": str(old_slot.id), "patient_id": patient["patient_id"]},
    )
    assert old_appt.status_code == 201

    holder = register(client, "Offer Holder", "race-offer-holder@test.demo")
    holder_appt = client.post(
        f"{API}/appointments",
        headers=holder["headers"],
        json={"slot_id": str(offer_slot.id), "patient_id": holder["patient_id"]},
    )
    assert holder_appt.status_code == 201
    join = client.post(
        f"{API}/waiting-list",
        headers=waiting["headers"],
        json={"affiliation_id": str(world["h1"]["aff"].id), "patient_id": waiting["patient_id"]},
    )
    assert join.status_code == 201
    cancel = client.post(
        f"{API}/appointments/{holder_appt.json()['data']['id']}/cancel",
        headers=holder["headers"],
        json={},
    )
    assert cancel.status_code == 200
    waiting_list = client.get(
        f"{API}/waiting-list?patient_id={waiting['patient_id']}",
        headers=waiting["headers"],
    ).json()["data"]
    assert len(waiting_list["offers"]) == 1
    offer_id = waiting_list["offers"][0]["id"]

    acceptance_locked = Event()
    allow_acceptance_commit = Event()
    from app.services import booking

    original_patient_busy = booking._patient_busy

    def pause_acceptance(session, patient_id, checked_slot, ignore=None):
        acceptance_locked.set()
        if not allow_acceptance_commit.wait(timeout=5):
            raise RuntimeError("Timed out waiting for acceptance commit")
        return original_patient_busy(session, patient_id, checked_slot, ignore)

    monkeypatch.setattr(booking, "_patient_busy", pause_acceptance)

    def run_acceptance():
        return client.post(
            f"{API}/waiting-list/offers/{offer_id}/accept",
            headers=waiting["headers"],
        )

    def run_reschedule():
        return client.post(
            f"{API}/appointments/{old_appt.json()['data']['id']}/reschedule",
            headers=patient["headers"],
            json={"new_slot_id": str(new_slot.id)},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        acceptance_future = pool.submit(run_acceptance)
        assert acceptance_locked.wait(timeout=5)
        reschedule_future = pool.submit(run_reschedule)
        reschedule_running = not reschedule_future.done()
        allow_acceptance_commit.set()
        acceptance_response = acceptance_future.result(timeout=5)
        reschedule_response = reschedule_future.result(timeout=5)

    assert reschedule_running
    assert acceptance_response.status_code == 201
    assert reschedule_response.status_code in (200, 409)


def test_cancellation_offer_generation_waits_for_waiting_acceptance_hospital_lock(client, db, world, monkeypatch):
    holder = register(client, "Cancellation Holder", "race-cancellation@test.demo")
    offer_holder = register(client, "Existing Offer Holder", "race-existing-offer@test.demo")
    waiting = register(client, "Cancellation Waiting", "race-cancellation-waiting@test.demo")

    cancel_slot = world["h1"]["slots"][0]
    existing_offer_slot = world["h1"]["slots"][1]

    cancellation_appt = client.post(
        f"{API}/appointments",
        headers=holder["headers"],
        json={"slot_id": str(cancel_slot.id), "patient_id": holder["patient_id"]},
    )
    assert cancellation_appt.status_code == 201
    existing_appt = client.post(
        f"{API}/appointments",
        headers=offer_holder["headers"],
        json={"slot_id": str(existing_offer_slot.id), "patient_id": offer_holder["patient_id"]},
    )
    assert existing_appt.status_code == 201

    join = client.post(
        f"{API}/waiting-list",
        headers=waiting["headers"],
        json={"affiliation_id": str(world["h1"]["aff"].id), "patient_id": waiting["patient_id"]},
    )
    assert join.status_code == 201

    existing_cancel = client.post(
        f"{API}/appointments/{existing_appt.json()['data']['id']}/cancel",
        headers=offer_holder["headers"],
        json={},
    )
    assert existing_cancel.status_code == 200
    waiting_list = client.get(
        f"{API}/waiting-list?patient_id={waiting['patient_id']}",
        headers=waiting["headers"],
    ).json()["data"]
    assert len(waiting_list["offers"]) == 1
    existing_offer_id = waiting_list["offers"][0]["id"]

    from app.services import waitlist

    offer_generation_locked = Event()
    allow_cancellation_commit = Event()
    original_offer_slot = waitlist.offer_slot

    def pause_offer_generation(*args, **kwargs):
        if kwargs.get("hospital_locked") and kwargs.get("slot_locked"):
            offer_generation_locked.set()
            if not allow_cancellation_commit.wait(timeout=5):
                raise RuntimeError("Timed out waiting for cancellation commit")
        return original_offer_slot(*args, **kwargs)

    monkeypatch.setattr(waitlist, "offer_slot", pause_offer_generation)

    def run_cancellation():
        return client.post(
            f"{API}/appointments/{cancellation_appt.json()['data']['id']}/cancel",
            headers=holder["headers"],
            json={},
        )

    def run_acceptance():
        return client.post(
            f"{API}/waiting-list/offers/{existing_offer_id}/accept",
            headers=waiting["headers"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancellation_future = pool.submit(run_cancellation)
        assert offer_generation_locked.wait(timeout=5)
        acceptance_future = pool.submit(run_acceptance)
        acceptance_running = not acceptance_future.done()
        allow_cancellation_commit.set()
        cancellation_response = cancellation_future.result(timeout=5)
        acceptance_response = acceptance_future.result(timeout=5)

    assert acceptance_running
    assert cancellation_response.status_code == 200
    assert acceptance_response.status_code == 201
