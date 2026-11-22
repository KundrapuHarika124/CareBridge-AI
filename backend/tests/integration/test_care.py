"""Journey 3: caregiver consent, granular permissions and revocation."""
from tests.integration.helpers import API, book, grant, register


def test_consent_flow_permissions_and_revocation(client, world):
    pat = register(client, "Lakshmi", "9000000001")
    care = register(client, "Sita", "sita@test.demo", role="CAREGIVER")
    slots = world["h1"]["slots"]
    rel_id = grant(client, care, pat, "9000000001", ["VIEW_APPOINTMENTS"])

    # View-only: can list, cannot book.
    assert client.get(f"{API}/appointments?patient_id={pat['patient_id']}", headers=care["headers"]).status_code == 200
    assert book(client, care, slots[0], patient_id=pat["patient_id"]).status_code == 404

    # Patient adds booking; the caregiver's very next request succeeds.
    r = client.patch(f"{API}/care/relationships/{rel_id}/permissions", headers=pat["headers"],
                     json={"permissions": ["VIEW_APPOINTMENTS", "BOOK_APPOINTMENTS"]})
    assert r.status_code == 200 and "BOOK_APPOINTMENTS" in r.json()["data"]["permissions"]
    booked = book(client, care, slots[0], patient_id=pat["patient_id"])
    assert booked.status_code == 201
    appt_id = booked.json()["data"]["id"]
    # Booking permission does not include cancelling.
    assert client.post(f"{API}/appointments/{appt_id}/cancel", headers=care["headers"], json={}).status_code == 404

    # Revocation applies to the next request.
    assert client.post(f"{API}/care/relationships/{rel_id}/revoke", headers=pat["headers"],
                       json={"reason": "No longer needed"}).status_code == 200
    assert client.get(f"{API}/appointments?patient_id={pat['patient_id']}", headers=care["headers"]).status_code == 404
    assert book(client, care, slots[1], patient_id=pat["patient_id"]).status_code == 404

    history = client.get(f"{API}/care/relationships/{rel_id}/history", headers=pat["headers"]).json()["data"]
    assert [h["action"] for h in history] == ["REQUESTED", "GRANTED", "MODIFIED", "REVOKED"]
    assert all(h["consent_text_version"] for h in history)


def test_patient_can_grant_fewer_permissions_than_requested(client, world):
    pat = register(client, "A", "a@test.demo")
    care = register(client, "C", "c@test.demo", role="CAREGIVER")
    client.post(f"{API}/care/requests", headers=care["headers"],
                json={"patient_identifier": "a@test.demo", "permissions": ["VIEW_APPOINTMENTS", "BOOK_APPOINTMENTS"]})
    rel = client.get(f"{API}/care/relationships", headers=pat["headers"]).json()["data"][0]
    assert rel["status"] == "REQUESTED" and rel["permissions"] == []
    r = client.post(f"{API}/care/relationships/{rel['id']}/approve", headers=pat["headers"],
                    json={"permissions": ["VIEW_APPOINTMENTS"]})
    assert r.json()["data"]["permissions"] == ["VIEW_APPOINTMENTS"]


def test_reject_and_unknown_patient_look_identical_to_caregiver(client, world):
    pat = register(client, "A", "a@test.demo")
    care = register(client, "C", "c@test.demo", role="CAREGIVER")
    body = {"permissions": ["VIEW_APPOINTMENTS"]}
    known = client.post(f"{API}/care/requests", headers=care["headers"], json={**body, "patient_identifier": "a@test.demo"})
    unknown = client.post(f"{API}/care/requests", headers=care["headers"], json={**body, "patient_identifier": "zz@test.demo"})
    assert known.status_code == unknown.status_code == 202
    assert known.json()["data"] == unknown.json()["data"]
    rel = client.get(f"{API}/care/relationships", headers=pat["headers"]).json()["data"][0]
    assert client.post(f"{API}/care/relationships/{rel['id']}/reject", headers=pat["headers"]).status_code == 200
    assert client.get(f"{API}/appointments?patient_id={pat['patient_id']}", headers=care["headers"]).status_code == 404


def test_only_the_patient_can_decide(client, world):
    pat = register(client, "A", "a@test.demo")
    other = register(client, "B", "b@test.demo")
    care = register(client, "C", "c@test.demo", role="CAREGIVER")
    client.post(f"{API}/care/requests", headers=care["headers"],
                json={"patient_identifier": "a@test.demo", "permissions": ["VIEW_APPOINTMENTS"]})
    rel = client.get(f"{API}/care/relationships", headers=pat["headers"]).json()["data"][0]
    approve = f"{API}/care/relationships/{rel['id']}/approve"
    body = {"permissions": ["VIEW_APPOINTMENTS"]}
    assert client.post(approve, headers=other["headers"], json=body).status_code == 404  # another patient
    assert client.post(approve, headers=care["headers"], json=body).status_code == 403  # the caregiver themself
    assert client.post(approve, headers=pat["headers"], json={"permissions": ["EVERYTHING"]}).status_code == 400
    assert client.post(approve, headers=pat["headers"], json={"permissions": []}).status_code == 400


def test_follow_up_and_intake_need_their_own_permissions(client, world):
    from tests.integration.helpers import login

    pat = register(client, "A", "a@test.demo")
    care = register(client, "C", "c@test.demo", role="CAREGIVER")
    appt = book(client, pat, world["h1"]["slots"][0]).json()["data"]
    doctor = login(client, "doctor1@test.demo")
    client.put(f"{API}/appointments/{appt['id']}/follow-up", headers=doctor["headers"],
               json={"instructions_text": "Rest for a week."})
    rel_id = grant(client, care, pat, "a@test.demo", ["VIEW_APPOINTMENTS"])
    base = f"{API}/appointments/{appt['id']}"
    assert client.get(f"{base}/follow-up", headers=care["headers"]).status_code == 404
    assert client.get(f"{base}/intake", headers=care["headers"]).status_code == 404
    client.patch(f"{API}/care/relationships/{rel_id}/permissions", headers=pat["headers"],
                 json={"permissions": ["VIEW_APPOINTMENTS", "VIEW_FOLLOW_UP_INFORMATION"]})
    r = client.get(f"{base}/follow-up", headers=care["headers"])
    assert r.status_code == 200 and r.json()["data"]["instructions_text"] == "Rest for a week."
    assert client.get(f"{base}/intake", headers=care["headers"]).status_code == 404
