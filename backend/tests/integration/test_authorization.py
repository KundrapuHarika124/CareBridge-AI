"""Journey 7: changing an ID in a URL or body never exposes someone else's data."""
import uuid

from tests.integration.helpers import API, book, login, register


def test_patient_cannot_read_or_change_another_patients_appointment(client, world):
    a, b = register(client, "A", "a@test.demo"), register(client, "B", "b@test.demo")
    appt = book(client, a, world["h1"]["slots"][0]).json()["data"]
    base = f"{API}/appointments/{appt['id']}"
    assert client.get(base, headers=b["headers"]).status_code == 404
    assert client.post(f"{base}/cancel", headers=b["headers"], json={}).status_code == 404
    assert client.post(f"{base}/reschedule", headers=b["headers"],
                       json={"new_slot_id": str(world["h1"]["slots"][1].id)}).status_code == 404
    for sub in ("intake", "summary", "follow-up", "notes"):
        assert client.get(f"{base}/{sub}", headers=b["headers"]).status_code == 404
    assert client.get(base, headers=a["headers"]).json()["data"]["status"] == "CONFIRMED"


def test_patient_cannot_book_or_list_for_another_patient_id(client, world):
    a, b = register(client, "A", "a@test.demo"), register(client, "B", "b@test.demo")
    assert book(client, b, world["h1"]["slots"][0], patient_id=a["patient_id"]).status_code == 404
    assert client.get(f"{API}/appointments?patient_id={a['patient_id']}", headers=b["headers"]).status_code == 404
    assert client.get(f"{API}/waiting-list?patient_id={a['patient_id']}", headers=b["headers"]).status_code == 404


def test_caregiver_without_consent_sees_nothing(client, world):
    pat = register(client, "A", "a@test.demo")
    care = register(client, "C", "c@test.demo", role="CAREGIVER")
    appt = book(client, pat, world["h1"]["slots"][0]).json()["data"]
    assert client.get(f"{API}/appointments?patient_id={pat['patient_id']}", headers=care["headers"]).status_code == 404
    assert client.get(f"{API}/appointments/{appt['id']}", headers=care["headers"]).status_code == 404
    assert book(client, care, world["h1"]["slots"][1], patient_id=pat["patient_id"]).status_code == 404


def test_hospital_admin_is_confined_to_own_hospital(client, world):
    admin1 = login(client, "admin1@test.demo")
    h1, h2 = world["h1"], world["h2"]
    own, other = f"{API}/admin/hospitals/{h1['hospital'].id}", f"{API}/admin/hospitals/{h2['hospital'].id}"
    assert client.get(f"{own}/overview", headers=admin1["headers"]).status_code == 200
    for path in ("", "/overview", "/departments", "/doctors", "/appointments"):
        assert client.get(f"{other}{path}", headers=admin1["headers"]).status_code == 404
    # Mixing an own hospital id with another hospital's resource ids is also refused.
    assert client.get(f"{own}/affiliations/{h2['aff'].id}/schedules", headers=admin1["headers"]).status_code == 404
    assert client.post(f"{own}/slots/{h2['slots'][0].id}/block", headers=admin1["headers"]).status_code == 404
    assert client.post(f"{own}/affiliations/{h2['aff'].id}/slots/generate", headers=admin1["headers"],
                       json={"days": 3}).status_code == 404


def test_admin_sees_logistics_but_no_clinical_content(client, world):
    pat = register(client, "A", "a@test.demo")
    appt = book(client, pat, world["h1"]["slots"][0]).json()["data"]
    client.put(f"{API}/appointments/{appt['id']}/intake", headers=pat["headers"], json={"answers": {"main_concern": "x"}})
    admin1 = login(client, "admin1@test.demo")
    rows = client.get(f"{API}/admin/hospitals/{world['h1']['hospital'].id}/appointments",
                      headers=admin1["headers"]).json()["data"]
    assert len(rows) == 1 and "reason_text" not in rows[0]
    for sub in ("intake", "summary", "follow-up", "notes"):
        assert client.get(f"{API}/appointments/{appt['id']}/{sub}", headers=admin1["headers"]).status_code == 404


def test_doctor_sees_only_own_appointments(client, world):
    pat = register(client, "A", "a@test.demo")
    appt = book(client, pat, world["h1"]["slots"][0]).json()["data"]
    doctor1, doctor2 = login(client, "doctor1@test.demo"), login(client, "doctor2@test.demo")
    assert client.get(f"{API}/appointments/{appt['id']}", headers=doctor1["headers"]).status_code == 200
    assert client.get(f"{API}/appointments/{appt['id']}", headers=doctor2["headers"]).status_code == 404
    assert client.put(f"{API}/appointments/{appt['id']}/notes", headers=doctor2["headers"],
                      json={"note_text": "x"}).status_code == 404
    assert client.post(f"{API}/appointments/{appt['id']}/complete", headers=doctor2["headers"]).status_code == 404


def test_role_restricted_routes(client, world):
    pat = register(client, "A", "a@test.demo")
    doctor1 = login(client, "doctor1@test.demo")
    hid = world["h1"]["hospital"].id
    assert client.get(f"{API}/admin/hospitals/{hid}/overview", headers=pat["headers"]).status_code == 403
    assert client.get(f"{API}/doctor/appointments", headers=pat["headers"]).status_code == 403
    assert client.post(f"{API}/care/requests", headers=pat["headers"],
                       json={"patient_identifier": "a@test.demo", "permissions": ["VIEW_APPOINTMENTS"]}).status_code == 403
    assert client.post(f"{API}/appointments", headers=doctor1["headers"],
                       json={"slot_id": str(world["h1"]["slots"][0].id), "patient_id": str(pat["patient_id"])}).status_code == 403


def test_unknown_ids_return_404_not_500(client, world):
    pat = register(client, "A", "a@test.demo")
    missing = uuid.uuid4()
    assert client.get(f"{API}/appointments/{missing}", headers=pat["headers"]).status_code == 404
    assert client.get(f"{API}/affiliations/{missing}/slots", headers=pat["headers"]).status_code == 404
    assert client.get(f"{API}/appointments/not-a-uuid", headers=pat["headers"]).status_code == 400


def test_unauthenticated_requests_are_refused(client, world):
    for path in ("/me", "/doctors", "/appointments", "/care/relationships", "/assistant/status", "/specialties"):
        assert client.get(f"{API}{path}").status_code == 401
