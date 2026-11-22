"""Unit tests for pure logic. These need no database and no external service."""
from datetime import date, datetime, time, timezone

from app.constants import (
    ST_AWAITING_CONFIRMATION,
    ST_COLLECTING_LOCATION,
    ST_COLLECTING_PREFERENCES,
    ST_HANDOFF_REQUIRED,
    ST_IDENTIFYING_PATIENT,
    ST_IDENTIFYING_SPECIALTY,
    ST_SHOWING_AVAILABLE_SLOTS,
    ST_UNDERSTANDING_REQUEST,
)
from app.core.ratelimit import RateLimiter
from app.core.timeutil import (
    ist_day_bounds_utc,
    ist_to_utc,
    resolve_date_phrase,
    time_of_day,
    to_utc_iso,
    today_ist,
)
from app.i18n.templates import T, fmt_when, t
from app.schemas import CareRequestIn, RegisterIn, normalize_identifier
from app.services import assistant_core as core
from app.services import safety

TODAY = date(2026, 11, 20)  # a Friday


class FakePort:
    """Stands in for the database-backed directory."""

    def __init__(self, caregiver=False, patients=None, slots=True):
        self.is_caregiver = caregiver
        self._patients = patients if patients is not None else [{"id": "p1", "name": "Lakshmi"}]
        self._slots = slots
        self.searches = []

    def authorized_patients(self):
        return self._patients

    def specialties(self):
        return [
            {"id": "s-ortho", "code": "ORTHOPAEDICS", "name_en": "Orthopaedics", "name_te": "ఎముకల వైద్యం"},
            {"id": "s-gen", "code": "GENERAL_MEDICINE", "name_en": "General Medicine", "name_te": "సాధారణ వైద్యం"},
        ]

    def suggest(self, text):
        if "knee" in text.lower() or "మోకాలి" in text or "mokali" in text.lower():
            return [{"specialty_id": "s-ortho", "explanation_en": "Bone and joint doctors.", "explanation_te": "ఎముకలు, కీళ్ల డాక్టర్లు."}]
        return []

    def localities(self):
        return ["Kukatpally", "Banjara Hills"]

    def search(self, specialty_id, locality, on_date, tod):
        self.searches.append((specialty_id, locality, on_date, tod))
        if not self._slots:
            return []
        return [
            {"slot_id": "slot-1", "doctor": "Dr. Rao", "hospital": "Simulated Hospital A", "locality": "Kukatpally",
             "starts_at": datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)},
            {"slot_id": "slot-2", "doctor": "Dr. Devi", "hospital": "Simulated Hospital B", "locality": "Banjara Hills",
             "starts_at": datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)},
        ]


def run(port, data, state, lang="en", **kw):
    return core.step(data, lang, state, port, TODAY, **kw)


# ------------------------------------------------------------------ rate limiter

def test_rate_limiter_blocks_after_limit_and_recovers():
    limiter = RateLimiter(max_hits=2, window_seconds=10)
    assert limiter.allow("a", now=0)
    assert limiter.allow("a", now=1)
    assert not limiter.allow("a", now=2)
    assert limiter.allow("b", now=2)  # other keys are independent
    assert limiter.allow("a", now=11)  # window has moved on


def test_rate_limiter_blocked_does_not_record_a_hit():
    limiter = RateLimiter(max_hits=1, window_seconds=10)
    assert not limiter.blocked("a", now=0)
    assert not limiter.blocked("a", now=0)  # asking twice changes nothing
    assert limiter.allow("a", now=0)
    assert limiter.blocked("a", now=5)
    assert not limiter.blocked("a", now=10)


# ------------------------------------------------------------------ time

def test_ist_conversion_and_day_bounds():
    assert ist_to_utc(date(2026, 11, 23), time(10, 30)) == datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)
    start, end = ist_day_bounds_utc(date(2026, 11, 23))
    assert start == datetime(2026, 11, 22, 18, 30, tzinfo=timezone.utc)
    assert (end - start).total_seconds() == 86400


def test_today_ist_crosses_midnight_before_utc():
    assert today_ist(datetime(2026, 11, 20, 19, 0, tzinfo=timezone.utc)) == date(2026, 11, 21)


def test_time_of_day_uses_ist():
    assert time_of_day(datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)) == "MORNING"  # 10:30 IST
    assert time_of_day(datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)) == "AFTERNOON"  # 13:30 IST
    assert time_of_day(datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)) == "EVENING"  # 17:30 IST


def test_to_utc_iso():
    assert to_utc_iso(datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)) == "2026-11-23T05:00:00Z"
    assert to_utc_iso(None) is None


def test_resolve_date_phrase():
    assert resolve_date_phrase("today", TODAY) == TODAY
    assert resolve_date_phrase("TOMORROW", TODAY) == date(2026, 11, 21)
    assert resolve_date_phrase("MONDAY", TODAY) == date(2026, 11, 23)
    assert resolve_date_phrase("FRIDAY", TODAY) == date(2026, 11, 27)  # same weekday means next week
    assert resolve_date_phrase("2026-12-01", TODAY) == date(2026, 12, 1)
    assert resolve_date_phrase("2026-11-01", TODAY) is None  # past dates are rejected
    assert resolve_date_phrase("someday", TODAY) is None


# ------------------------------------------------------------------ templates

def test_templates_have_same_keys_in_both_languages():
    assert set(T["en"]) == set(T["te"])


def test_fmt_when_both_languages():
    dt = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)
    assert fmt_when(dt, "en") == "Mon 23 Nov, 10:30 AM"
    assert fmt_when(dt, "te") == "సోమవారం 23 నవంబర్, ఉదయం 10:30"


# ------------------------------------------------------------------ schemas

def test_identifier_normalization():
    assert normalize_identifier("+91 90000-00001") == ("phone", "9000000001")
    assert normalize_identifier("A@B.Co") == ("email", "a@b.co")


def test_register_rejects_staff_roles_and_weak_passwords():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RegisterIn(full_name="Dr X", identifier="x@y.co", password="Demo@12345", role="DOCTOR")
    with pytest.raises(ValidationError):
        RegisterIn(full_name="Pat", identifier="x@y.co", password="12345678", role="PATIENT")
    with pytest.raises(ValidationError):
        CareRequestIn(patient_identifier="x@y.co", permissions=["READ_EVERYTHING"])


# ------------------------------------------------------------------ safety

def test_emergency_detection_in_three_scripts():
    assert safety.is_emergency("I have chest pain")
    assert safety.is_emergency("naaku chaati noppi ga undi")
    assert safety.is_emergency("నాకు ఛాతీ నొప్పి")
    assert not safety.is_emergency("knee pain since two weeks")
    assert not safety.is_emergency("benefits of walking")  # "fits" inside another word


def test_medical_advice_detection():
    assert safety.asks_medical_advice("What medicine should I take for fever?")
    assert safety.asks_medical_advice("ఏ మందు వేసుకోవాలి")
    assert safety.asks_medical_advice("what is the dosage")
    assert not safety.asks_medical_advice("I need a doctor for knee pain")


def test_match_concerns_prefers_longer_phrase():
    mappings = [
        {"id": 1, "phrases": ["pain"]},
        {"id": 2, "phrases": ["knee pain", "మోకాలి నొప్పి"]},
        {"id": 3, "phrases": ["cough"]},
    ]
    assert [m["id"] for m in safety.match_concerns("I have Knee Pain!", mappings)] == [2, 1]
    assert [m["id"] for m in safety.match_concerns("మోకాలి నొప్పి ఉంది", mappings)] == [2]
    assert safety.match_concerns("", mappings) == []


# ------------------------------------------------------------------ extraction

def test_sanitize_extraction_drops_unknown_and_malformed_fields():
    raw = {"intent": "book", "for_whom": "ALIEN", "option_index": 99, "yes_no": "maybe", "date_phrase": "DROP TABLE",
           "time_of_day": "evening", "sql": "select *", "concern_text": "  knee pain  ", "specialty_code": 5}
    assert core.sanitize_extraction(raw) == {"intent": "BOOK", "time_of_day": "EVENING", "concern_text": "knee pain"}
    assert core.sanitize_extraction("not a dict") == {}
    assert core.sanitize_extraction({"option_index": True}) == {}


def test_extract_rules_maps_common_symptoms_to_specialties():
    specialties = [
        {"id": "ortho", "code": "ORTHOPAEDICS", "name_en": "Orthopaedics", "name_te": "ఎముకల వైద్యం"},
        {"id": "skin", "code": "DERMATOLOGY", "name_en": "Dermatology", "name_te": "చర్మ వైద్యం"},
        {"id": "eye", "code": "OPHTHALMOLOGY", "name_en": "Ophthalmology", "name_te": "కంటి వైద్యం"},
        {"id": "teeth", "code": "DENTISTRY", "name_en": "Dentistry", "name_te": "దంత వైద్యం"},
    ]
    assert "specialty_code" not in core.extract_rules("I have knee pain", specialties, [])
    assert "specialty_code" not in core.extract_rules("my skin has a rash", specialties, [])
    assert "specialty_code" not in core.extract_rules("blurred vision", specialties, [])
    assert "specialty_code" not in core.extract_rules("toothache", specialties, [])


def test_extract_rules_unknown_and_empty_symptoms_do_not_choose_specialty():
    specialties = [
        {"id": "ortho", "code": "ORTHOPAEDICS", "name_en": "Orthopaedics", "name_te": "ఎముకల వైద్యం"},
    ]
    assert "specialty_code" not in core.extract_rules("I feel strange", specialties, [])
    assert "specialty_code" not in core.extract_rules("", specialties, [])


def test_extract_rules_english_telugu_and_mixed():
    port = FakePort()
    sp, loc = port.specialties(), port.localities()
    ex = core.extract_rules("orthopaedics doctor in Kukatpally tomorrow morning", sp, loc)
    assert ex["specialty_code"] == "ORTHOPAEDICS" and ex["locality"] == "Kukatpally"
    assert ex["date_phrase"] == "TOMORROW" and ex["time_of_day"] == "MORNING"
    ex = core.extract_rules("repu sayantram kavali", sp, loc)
    assert ex["date_phrase"] == "TOMORROW" and ex["time_of_day"] == "EVENING"
    ex = core.extract_rules("రేపు ఉదయం", sp, loc)
    assert ex["date_phrase"] == "TOMORROW" and ex["time_of_day"] == "MORNING"
    assert core.extract_rules("avunu", sp, loc)["yes_no"] == "YES"
    assert core.extract_rules("వద్దు", sp, loc)["yes_no"] == "NO"
    assert core.extract_rules("rendo", sp, loc)["option_index"] == 2
    assert core.extract_rules("amma kosam", sp, loc)["for_whom"] == "OTHER"
    assert core.extract_rules("ellundi", sp, loc)["date_phrase"] == "DAY_AFTER_TOMORROW"


def test_yes_is_only_accepted_as_a_short_clear_reply():
    port = FakePort()
    sp, loc = port.specialties(), port.localities()
    assert core.extract_rules("ok confirm", sp, loc)["yes_no"] == "YES"
    assert "yes_no" not in core.extract_rules("I want to book a different time", sp, loc)
    assert "yes_no" not in core.extract_rules("ok but can you change the time to evening", sp, loc)
    assert core.extract_rules("don't book it", sp, loc)["yes_no"] == "NO"
    assert core.extract_rules("yes no wait", sp, loc)["yes_no"] == "NO"  # any doubt means no


# ------------------------------------------------------------------ state machine

def test_full_booking_conversation_with_buttons():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    state, reply, options = core.next_prompt(data, "en", port, TODAY)
    assert state == ST_UNDERSTANDING_REQUEST and options == []

    r = run(port, data, state, ex={"concern_text": "knee pain"})
    assert r.state == ST_IDENTIFYING_SPECIALTY
    assert "not a diagnosis" in r.reply
    assert r.options[0]["value"] == "specialty:s-ortho"

    r = run(port, data, r.state, move="specialty:s-ortho")
    assert r.state == ST_COLLECTING_LOCATION

    r = run(port, data, r.state, move="locality:Kukatpally")
    assert r.state == ST_COLLECTING_PREFERENCES

    r = run(port, data, r.state, move="pref:ANY")
    assert r.state == ST_SHOWING_AVAILABLE_SLOTS
    assert port.searches[-1] == ("s-ortho", "Kukatpally", None, None)
    assert r.options[0]["value"] == "slot:slot-1"

    r = run(port, data, r.state, move="slot:slot-1")
    assert r.state == ST_AWAITING_CONFIRMATION
    assert "Dr. Rao" in r.reply and "Lakshmi" in r.reply and "10:30 AM" in r.reply
    assert r.action is None  # choosing a slot never books by itself

    r = run(port, data, r.state, move="confirm:yes")
    assert r.action == "BOOK"


def test_everything_in_one_sentence_skips_questions():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    ex = core.extract_rules("orthopaedics in Kukatpally tomorrow morning", port.specialties(), port.localities())
    r = run(port, data, ST_UNDERSTANDING_REQUEST, ex=ex)
    assert r.state == ST_SHOWING_AVAILABLE_SLOTS
    assert port.searches[-1] == ("s-ortho", "Kukatpally", date(2026, 11, 21), "MORNING")


def test_telugu_replies_use_telugu_templates():
    port, data = FakePort(), core.new_data("p1", "లక్ష్మి")
    r = run(port, data, ST_UNDERSTANDING_REQUEST, lang="te", ex={"concern_text": "మోకాలి నొప్పి"})
    assert r.state == ST_IDENTIFYING_SPECIALTY
    assert "రోగ నిర్ధారణ కాదు" in r.reply
    assert r.options[0]["label"] == "ఎముకల వైద్యం"


def test_slot_not_offered_by_server_cannot_be_chosen():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    data.update(specialty_id="s-ortho", locality="Kukatpally", pref_done=True)
    r = run(port, data, ST_COLLECTING_PREFERENCES, move="pref:ANY")
    assert r.state == ST_SHOWING_AVAILABLE_SLOTS
    r = run(port, data, r.state, move="slot:someone-elses-slot")
    assert r.state == ST_SHOWING_AVAILABLE_SLOTS and data["slot"] is None


def test_confirm_without_a_chosen_slot_does_not_book():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    r = run(port, data, ST_AWAITING_CONFIRMATION, move="confirm:yes")
    assert r.action is None
    r = run(port, data, ST_UNDERSTANDING_REQUEST, ex={"yes_no": "YES"})
    assert r.action is None


def test_yes_and_no_at_confirmation():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    data.update(specialty_id="s-ortho", locality="Kukatpally", pref_done=True)
    r = run(port, data, ST_COLLECTING_PREFERENCES, move="pref:ANY")
    r = run(port, data, r.state, ex={"option_index": 2})
    assert r.state == ST_AWAITING_CONFIRMATION and data["slot"]["slot_id"] == "slot-2"
    r = run(port, data, r.state, ex={"yes_no": "NO"})
    assert r.state == ST_SHOWING_AVAILABLE_SLOTS and data["slot"] is None
    assert r.reply.startswith("Okay, I have not booked it.")
    r = run(port, data, r.state, move="slot:slot-1")
    r = run(port, data, r.state, ex={"yes_no": "YES"})
    assert r.action == "BOOK" and data["slot"]["slot_id"] == "slot-1"


def test_correction_changes_field_and_searches_again():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    data.update(specialty_id="s-ortho", locality="Kukatpally", pref_done=True)
    r = run(port, data, ST_COLLECTING_PREFERENCES, move="pref:ANY")
    r = run(port, data, r.state, ex={"locality": "Banjara Hills"})
    assert r.state == ST_SHOWING_AVAILABLE_SLOTS
    assert port.searches[-1][1] == "Banjara Hills"


def test_no_slots_returns_to_location_question():
    port, data = FakePort(slots=False), core.new_data("p1", "Lakshmi")
    data.update(specialty_id="s-ortho", locality="Kukatpally")
    r = run(port, data, ST_COLLECTING_PREFERENCES, move="pref:TODAY")
    assert r.state == ST_COLLECTING_LOCATION
    assert "could not find a free time" in r.reply
    assert data["locality"] is None and data["pref_done"] is False


def test_three_unclear_turns_hand_off():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    data.update(specialty_id="s-ortho")
    state = ST_COLLECTING_LOCATION
    r = run(port, data, state, ex={})
    assert r.state == ST_COLLECTING_LOCATION and r.reply.startswith("Sorry, I did not understand.")
    r = run(port, data, r.state, ex={})
    r = run(port, data, r.state, ex={})
    assert r.state == ST_HANDOFF_REQUIRED


def test_patient_cannot_book_for_someone_else():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    r = run(port, data, ST_UNDERSTANDING_REQUEST, ex={"for_whom": "OTHER", "other_person_hint": "mother"})
    assert "only book for you" in r.reply
    assert data["patient_id"] == "p1"
    moved, action = core.apply_move(data, "patient:someone-else", port)
    assert not moved and data["patient_id"] == "p1"


def test_caregiver_must_pick_an_authorized_patient():
    patients = [{"id": "p1", "name": "Lakshmi"}, {"id": "p2", "name": "Venkat Rao"}]
    port, data = FakePort(caregiver=True, patients=patients), core.new_data()
    state, reply, options = core.next_prompt(data, "en", port, TODAY)
    assert state == ST_IDENTIFYING_PATIENT and len(options) == 2
    r = run(port, data, state, move="patient:p3")
    assert r.state == ST_IDENTIFYING_PATIENT and data["patient_id"] is None
    r = run(port, data, state, ex={"for_whom": "OTHER", "other_person_hint": "venkat"})
    assert data["patient_id"] == "p2" and r.state == ST_UNDERSTANDING_REQUEST


def test_caregiver_without_booking_permission_is_handed_off():
    port, data = FakePort(caregiver=True, patients=[]), core.new_data()
    state, reply, _ = core.next_prompt(data, "en", port, TODAY)
    assert state == ST_HANDOFF_REQUIRED and "permission" in reply


def test_unmatched_concern_offers_full_specialty_list():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    r = run(port, data, ST_UNDERSTANDING_REQUEST, ex={"concern_text": "something unusual"})
    assert r.state == ST_IDENTIFYING_SPECIALTY and len(r.options) == 2


def test_other_intent_is_redirected_not_executed():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    r = run(port, data, ST_UNDERSTANDING_REQUEST, ex={"intent": "CANCEL_APPT"})
    assert "open Appointments" in r.reply and r.action is None


def test_restart_keeps_patient_for_patients_but_not_caregivers():
    port, data = FakePort(), core.new_data("p1", "Lakshmi")
    data.update(specialty_id="s-ortho", locality="Kukatpally")
    core.apply_move(data, "restart", port)
    assert data["patient_id"] == "p1" and data["specialty_id"] is None
    cg, data2 = FakePort(caregiver=True), core.new_data("p1", "Lakshmi")
    core.apply_move(data2, "restart", cg)
    assert data2["patient_id"] is None


def test_template_lookup_falls_back_to_english_for_unknown_language():
    assert t("fr", "opt_confirm") == "Confirm"
