from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from tests.integration.helpers import API, book, make_slot, register


def test_book_and_see_it_on_dashboard(client, world):
    pat = register(client, "Lakshmi", "9000000001")
    slot = world["h1"]["slots"][0]
    r = book(client, pat, slot)
    assert r.status_code == 201, r.text
    appt = r.json()["data"]
    assert appt["status"] == "CONFIRMED" and appt["hospital"]["is_simulated"] is True
    listed = client.get(f"{API}/appointments?scope=upcoming", headers=pat["headers"]).json()["data"]
    assert [a["id"] for a in listed] == [appt["id"]]
    notes = client.get(f"{API}/me/notifications", headers=pat["headers"]).json()["data"]
    assert notes[0]["type"] == "APPOINTMENT_BOOKED"


def test_second_booking_of_same_slot_conflicts_with_alternatives(client, world):
    a, b = register(client, "A", "a@test.demo"), register(client, "B", "b@test.demo")
    slot = world["h1"]["slots"][0]
    assert book(client, a, slot).status_code == 201
    r = book(client, b, slot)
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["code"] == "SLOT_UNAVAILABLE" and len(error["details"]["alternatives"]) >= 1


def test_idempotent_retry_returns_same_appointment(client, world):
    pat = register(client, "A", "a@test.demo")
    slot = world["h1"]["slots"][0]
    first = book(client, pat, slot, key="retry-1").json()["data"]
    second = book(client, pat, slot, key="retry-1")
    assert second.status_code == 201 and second.json()["data"]["id"] == first["id"]


def test_past_or_blocked_slot_cannot_be_booked(client, world, db):
    pat = register(client, "A", "a@test.demo")
    aff = world["h1"]["aff"]
    assert book(client, pat, make_slot(db, aff, -2)).status_code == 409
    assert book(client, pat, make_slot(db, aff, 50, status="BLOCKED")).status_code == 409


def test_cancel_frees_the_slot(client, world):
    a, b = register(client, "A", "a@test.demo"), register(client, "B", "b@test.demo")
    slot = world["h1"]["slots"][0]
    appt = book(client, a, slot).json()["data"]
    r = client.post(f"{API}/appointments/{appt['id']}/cancel", headers=a["headers"], json={"reason": "Changed plans"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "CANCELLED"
    assert book(client, b, slot).status_code == 201


def test_reschedule_moves_the_appointment(client, world):
    pat = register(client, "A", "a@test.demo")
    old_slot, new_slot = world["h1"]["slots"][0], world["h1"]["slots"][1]
    appt = book(client, pat, old_slot).json()["data"]
    r = client.post(f"{API}/appointments/{appt['id']}/reschedule", headers=pat["headers"],
                    json={"new_slot_id": str(new_slot.id)})
    assert r.status_code == 200, r.text
    new = r.json()["data"]
    assert new["slot_id"] == str(new_slot.id) and new["rescheduled_from_id"] == appt["id"]
    old = client.get(f"{API}/appointments/{appt['id']}", headers=pat["headers"]).json()["data"]
    assert old["status"] == "RESCHEDULED"


def test_failed_reschedule_leaves_original_untouched(client, world):
    a, b = register(client, "A", "a@test.demo"), register(client, "B", "b@test.demo")
    slot_a, slot_b = world["h1"]["slots"][0], world["h1"]["slots"][1]
    appt = book(client, a, slot_a).json()["data"]
    assert book(client, b, slot_b).status_code == 201
    r = client.post(f"{API}/appointments/{appt['id']}/reschedule", headers=a["headers"],
                    json={"new_slot_id": str(slot_b.id)})
    assert r.status_code == 409
    still = client.get(f"{API}/appointments/{appt['id']}", headers=a["headers"]).json()["data"]
    assert still["status"] == "CONFIRMED" and still["slot_id"] == str(slot_a.id)


def test_twenty_concurrent_bookings_give_exactly_one_success(client, world):
    """Journey 6: two (here twenty) users cannot book the same slot."""
    from app.core import errors
    from app.core.database import SessionLocal
    from app.models import Appointment, Patient, User
    from app.services import booking

    slot_id = world["h1"]["slots"][2].id
    import uuid

    patients = [uuid.UUID(register(client, f"P{i}", f"p{i}@test.demo")["patient_id"]) for i in range(20)]

    def attempt(patient_id):
        session = SessionLocal()
        try:
            patient = session.get(Patient, patient_id)
            actor = session.get(User, patient.user_id)
            booking.book(session, actor=actor, patient=patient, slot_id=slot_id)
            return "ok"
        except errors.AppError as exc:
            return exc.code
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt, patients))
    assert results.count("ok") == 1
    assert results.count("SLOT_UNAVAILABLE") == 19
    session = SessionLocal()
    try:
        active = session.scalar(
            select(func.count(Appointment.id)).where(Appointment.slot_id == slot_id, Appointment.status == "CONFIRMED")
        )
    finally:
        session.close()
    assert active == 1
