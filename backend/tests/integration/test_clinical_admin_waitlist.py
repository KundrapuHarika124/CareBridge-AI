"""Journeys 4 and 5, plus notifications and the waiting list."""
from tests.integration.helpers import API, PASSWORD, book, login, make_slot, register


def test_intake_summary_review_and_doctor_workflow(client, world):
    from app.integrations import llm

    pat = register(client, "A", "a@test.demo")
    appt = book(client, pat, world["h1"]["slots"][0]).json()["data"]
    base = f"{API}/appointments/{appt['id']}"
    doctor = login(client, "doctor1@test.demo")
    approved = client.post(API + "/doctor/appointments/" + appt["id"] + "/approve", headers=doctor["headers"])
    assert approved.status_code == 200 and approved.json()["data"]["status"] == "CONFIRMED"

    intake = client.get(f"{base}/intake", headers=pat["headers"]).json()["data"]
    assert intake["can_edit"] and len(intake["questionnaire"]["questions"]) == 2
    saved = client.put(f"{base}/intake", headers=pat["headers"],
                       json={"answers": {"main_concern": "Knee pain when climbing stairs", "duration": "2 weeks",
                                         "not_a_question": "dropped"}}).json()["data"]
    assert set(saved["answers"]) == {"main_concern", "duration"}

    # No model configured: the summary is refused, never invented. Answers stay available.
    r = client.post(f"{base}/summary", headers=pat["headers"])
    assert r.status_code == 503 and r.json()["error"]["code"] == "AI_UNAVAILABLE"
    assert client.get(f"{base}/intake", headers=doctor["headers"]).json()["data"]["answers"]["duration"] == "2 weeks"

    llm.set_llm(llm.MockLLM())
    summary = client.post(f"{base}/summary", headers=pat["headers"]).json()["data"]
    assert summary["label"] == "AI-generated" and summary["patient_reviewed_at"] is None
    # Release gate: the doctor does not see it until the patient has reviewed it.
    assert client.get(f"{base}/summary", headers=doctor["headers"]).json()["data"] is None
    client.patch(f"{base}/summary", headers=pat["headers"],
                 json={"content": {"reason_for_visit": "Knee pain on stairs"}, "mark_reviewed": True})
    seen = client.get(f"{base}/summary", headers=doctor["headers"]).json()["data"]
    assert seen["content"]["reason_for_visit"] == "Knee pain on stairs" and seen["patient_edited"] is True
    assert seen["source"] == "AI" and seen["model_name"]

    corrected = client.patch(f"{base}/summary", headers=doctor["headers"],
                             json={"clinician_correction": "Pain is in the left knee."}).json()["data"]
    assert corrected["clinician_correction"] == "Pain is in the left knee."

    note = client.put(f"{base}/notes", headers=doctor["headers"], json={"note_text": "Examined."}).json()["data"]
    assert note["label"] == "Clinician-authored"
    assert client.get(f"{base}/notes", headers=pat["headers"]).status_code == 404  # notes are clinician-only

    client.put(f"{base}/follow-up", headers=doctor["headers"],
               json={"instructions_text": "Review in two weeks.", "next_visit_date": "2027-01-10"})
    follow = client.get(f"{base}/follow-up", headers=pat["headers"]).json()["data"]
    assert follow["instructions_text"] == "Review in two weeks." and follow["label"] == "Clinician-authored"

    schedule = client.get(f"{API}/doctor/appointments?on_date={appt['starts_at'][:10]}", headers=doctor["headers"])
    assert schedule.status_code == 200
    done = client.post(f"{base}/complete", headers=doctor["headers"]).json()["data"]
    assert done["status"] == "COMPLETED"
    assert client.post(f"{base}/complete", headers=doctor["headers"]).status_code == 409
    types = {n["type"] for n in client.get(f"{API}/me/notifications", headers=pat["headers"]).json()["data"]}
    assert {"APPOINTMENT_REQUESTED", "APPOINTMENT_APPROVED", "FOLLOW_UP_ADDED"} <= types


def test_changing_answers_discards_the_old_summary(client, world):
    from app.integrations import llm

    llm.set_llm(llm.MockLLM())
    pat = register(client, "A", "a@test.demo")
    appt = book(client, pat, world["h1"]["slots"][0]).json()["data"]
    base = f"{API}/appointments/{appt['id']}"
    client.put(f"{base}/intake", headers=pat["headers"], json={"answers": {"main_concern": "First"}})
    client.post(f"{base}/summary", headers=pat["headers"])
    client.put(f"{base}/intake", headers=pat["headers"], json={"answers": {"main_concern": "Second"}})
    assert client.get(f"{base}/summary", headers=pat["headers"]).json()["data"] is None


def test_hospital_admin_manages_doctors_schedules_and_slots(client, world):
    admin = login(client, "admin1@test.demo")
    hid = world["h1"]["hospital"].id
    base = f"{API}/admin/hospitals/{hid}"
    h = admin["headers"]

    dept = client.post(f"{base}/departments", headers=h, json={"name": "General Medicine"})
    assert dept.status_code == 201
    assert client.post(f"{base}/departments", headers=h, json={"name": "general medicine"}).status_code == 409

    body = {"full_name": "Dr. New (Demo)", "identifier": "newdoc@test.demo", "qualifications": "MBBS",
            "department_id": dept.json()["data"]["id"], "specialty_id": str(world["specialty_general"].id),
            "consultation_fee": 400}
    assert client.post(f"{base}/doctors", headers=h, json=body).status_code == 400  # password needed for a new account
    created = client.post(f"{base}/doctors", headers=h, json={**body, "password": PASSWORD})
    assert created.status_code == 201, created.text
    aff_id = created.json()["data"]["affiliation_id"]
    assert login(client, "newdoc@test.demo")["user"]["role"] == "DOCTOR"

    for weekday in range(7):
        r = client.post(f"{base}/affiliations/{aff_id}/schedules", headers=h,
                        json={"weekday": weekday, "start_time": "10:00", "end_time": "12:00", "slot_minutes": 30})
        assert r.status_code == 201, r.text
    assert client.post(f"{base}/affiliations/{aff_id}/schedules", headers=h,
                       json={"weekday": 0, "start_time": "11:00", "end_time": "13:00"}).status_code == 409
    assert client.post(f"{base}/affiliations/{aff_id}/schedules", headers=h,
                       json={"weekday": 1, "start_time": "15:00", "end_time": "14:00"}).status_code == 400

    generated = client.post(f"{base}/affiliations/{aff_id}/slots/generate", headers=h, json={"days": 7}).json()["data"]
    assert 20 <= generated["created"] <= 28  # 4 per day for 7 days, minus any already past today
    again = client.post(f"{base}/affiliations/{aff_id}/slots/generate", headers=h, json={"days": 7}).json()["data"]
    assert again["created"] == 0  # generating twice creates nothing new

    pat = register(client, "A", "a@test.demo")
    open_slots = client.get(f"{API}/affiliations/{aff_id}/slots", headers=pat["headers"]).json()["data"]
    assert len(open_slots) == generated["created"]
    slot_id = open_slots[0]["id"]
    assert client.post(f"{base}/slots/{slot_id}/block", headers=h).json()["data"]["status"] == "BLOCKED"
    assert slot_id not in [s["id"] for s in client.get(f"{API}/affiliations/{aff_id}/slots", headers=pat["headers"]).json()["data"]]
    assert client.post(f"{base}/slots/{slot_id}/unblock", headers=h).json()["data"]["status"] == "AVAILABLE"

    r = client.patch(f"{base}/affiliations/{aff_id}", headers=h, json={"consultation_fee": 450, "is_active": False})
    assert r.json()["data"]["is_active"] is False
    assert aff_id not in [d["affiliation_id"] for d in client.get(f"{API}/doctors", headers=pat["headers"]).json()["data"]]


def test_admin_cancellation_needs_a_reason_and_notifies_patient(client, world):
    pat = register(client, "A", "a@test.demo")
    appt = book(client, pat, world["h1"]["slots"][0]).json()["data"]
    admin = login(client, "admin1@test.demo")
    url = f"{API}/admin/hospitals/{world['h1']['hospital'].id}/appointments/{appt['id']}/cancel"
    assert client.post(url, headers=admin["headers"], json={}).status_code == 400
    r = client.post(url, headers=admin["headers"], json={"reason": "Doctor unavailable"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "CANCELLED"
    types = [n["type"] for n in client.get(f"{API}/me/notifications", headers=pat["headers"]).json()["data"]]
    assert "APPOINTMENT_CANCELLED" in types
    overview = client.get(f"{API}/admin/hospitals/{world['h1']['hospital'].id}/overview", headers=admin["headers"]).json()["data"]
    assert overview["cancelled_last_7_days"] == 1 and overview["active_doctors"] == 1


def test_waiting_list_offer_hold_accept_and_decline(client, world, db):
    holder = register(client, "Holder", "h@test.demo")
    first, second = register(client, "First", "f@test.demo"), register(client, "Second", "s@test.demo")
    outsider = register(client, "Outsider", "o@test.demo")
    aff = world["h1"]["aff"]
    slot = make_slot(db, aff, 200)
    appt = book(client, holder, slot).json()["data"]
    for who in (first, second):
        r = client.post(f"{API}/waiting-list", headers=who["headers"],
                        json={"affiliation_id": str(aff.id), "patient_id": who["patient_id"]})
        assert r.status_code == 201

    client.post(f"{API}/appointments/{appt['id']}/cancel", headers=holder["headers"], json={})
    # The freed slot is held for the first person in line; nobody else can take it.
    assert book(client, outsider, slot).status_code == 409
    wl_first = client.get(f"{API}/waiting-list?patient_id={first['patient_id']}", headers=first["headers"]).json()["data"]
    assert len(wl_first["offers"]) == 1
    wl_second = client.get(f"{API}/waiting-list?patient_id={second['patient_id']}", headers=second["headers"]).json()["data"]
    assert wl_second["offers"] == []
    offer_id = wl_first["offers"][0]["id"]
    # Someone else cannot act on the offer.
    assert client.post(f"{API}/waiting-list/offers/{offer_id}/accept", headers=second["headers"]).status_code == 404

    # First declines: the offer passes to the second person.
    assert client.post(f"{API}/waiting-list/offers/{offer_id}/decline", headers=first["headers"]).status_code == 200
    wl_second = client.get(f"{API}/waiting-list?patient_id={second['patient_id']}", headers=second["headers"]).json()["data"]
    assert len(wl_second["offers"]) == 1
    accepted = client.post(f"{API}/waiting-list/offers/{wl_second['offers'][0]['id']}/accept", headers=second["headers"])
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["data"]["slot_id"] == str(slot.id)
    # Accepting twice does not create a second booking.
    assert client.post(f"{API}/waiting-list/offers/{wl_second['offers'][0]['id']}/accept",
                       headers=second["headers"]).status_code == 409
    assert len(client.get(f"{API}/appointments", headers=second["headers"]).json()["data"]) == 1


def test_expired_offer_releases_the_slot(client, world, db):
    from datetime import timedelta

    from app.core.timeutil import utcnow
    from app.models import WaitingListOffer
    from app.services import waitlist

    holder, waiting = register(client, "Holder", "h@test.demo"), register(client, "Waiting", "w@test.demo")
    outsider = register(client, "Outsider", "o@test.demo")
    aff = world["h1"]["aff"]
    slot = make_slot(db, aff, 300)
    appt = book(client, holder, slot).json()["data"]
    client.post(f"{API}/waiting-list", headers=waiting["headers"],
                json={"affiliation_id": str(aff.id), "patient_id": waiting["patient_id"]})
    client.post(f"{API}/appointments/{appt['id']}/cancel", headers=holder["headers"], json={})
    offer = db.query(WaitingListOffer).one()
    offer.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert waitlist.expire_due(db) == 1
    assert book(client, outsider, slot).status_code == 201  # back in general availability


def test_reminder_job_notifies_patient_once(client, world, db):
    from app.services import jobs

    pat = register(client, "A", "a@test.demo")
    soon = make_slot(db, world["h1"]["aff"], 3)
    appt = book(client, pat, soon).json()["data"]
    assert jobs.send_reminders(db) == 0
    doctor = login(client, "doctor1@test.demo")
    approved = client.post(API + "/doctor/appointments/" + appt["id"] + "/approve", headers=doctor["headers"])
    assert approved.status_code == 200
    assert jobs.send_reminders(db) == 1
    assert jobs.send_reminders(db) == 0
    types = [n["type"] for n in client.get(f"{API}/me/notifications", headers=pat["headers"]).json()["data"]]
    assert types.count("APPOINTMENT_REMINDER") == 1
    assert client.post(f"{API}/me/notifications/read-all", headers=pat["headers"]).status_code == 200
    assert client.get(f"{API}/me/notifications?unread_only=true", headers=pat["headers"]).json()["data"] == []
