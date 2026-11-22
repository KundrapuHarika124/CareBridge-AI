"""Conversation state machine for the booking assistant. Pure logic: no database, no network.

Design
- The language model (or the rule-based extractor below) only turns a message into a small
  dict of fields. It cannot act.
- This module decides what happens next and writes every reply from templates.
- Every value that matters (patient, specialty, locality, slot) is checked against what the
  `port` says exists and is allowed. Anything else is ignored.
- The only action it can request is "BOOK", and only from AWAITING_CONFIRMATION with a slot
  that the server itself offered. The service layer performs the booking.

`port` is any object with:
    is_caregiver: bool
    authorized_patients() -> [{"id": str, "name": str}]
    specialties() -> [{"id": str, "code": str, "name_en": str, "name_te": str}]
    suggest(text) -> [{"specialty_id": str, "explanation_en": str, "explanation_te": str}]
    localities() -> [str]
    search(specialty_id, locality, on_date, tod) -> [{"slot_id", "doctor", "hospital", "locality", "starts_at": datetime}]
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from app.constants import (
    MAX_UNCLEAR_TURNS,
    ST_AWAITING_CONFIRMATION,
    ST_COLLECTING_LOCATION,
    ST_COLLECTING_PREFERENCES,
    ST_HANDOFF_REQUIRED,
    ST_IDENTIFYING_PATIENT,
    ST_IDENTIFYING_SPECIALTY,
    ST_SHOWING_AVAILABLE_SLOTS,
    ST_UNDERSTANDING_REQUEST,
)
from app.core.timeutil import WEEKDAYS, resolve_date_phrase
from app.i18n.templates import fmt_when, t
from app.services.safety import normalize

ANY = "ANY"
_INTENTS = {"BOOK", "CANCEL_APPT", "RESCHEDULE", "VIEW", "OTHER"}
_TODS = {"MORNING", "AFTERNOON", "EVENING"}
_DATE_PHRASES = {"TODAY", "TOMORROW", "DAY_AFTER_TOMORROW", *WEEKDAYS}


@dataclass
class Result:
    state: str
    reply: str
    options: list = field(default_factory=list)
    action: str | None = None  # "BOOK" or None


# ---------------------------------------------------------------- extraction

def sanitize_extraction(raw) -> dict:
    """Keep only known keys with expected types. Model output is untrusted input."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}

    def text_of(key, limit):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()[:limit]

    intent = raw.get("intent")
    if isinstance(intent, str) and intent.upper() in _INTENTS:
        out["intent"] = intent.upper()
    who = raw.get("for_whom")
    if isinstance(who, str) and who.upper() in ("SELF", "OTHER"):
        out["for_whom"] = who.upper()
    text_of("other_person_hint", 80)
    text_of("concern_text", 300)
    text_of("specialty_code", 40)
    text_of("locality", 80)
    phrase = raw.get("date_phrase")
    if isinstance(phrase, str):
        p = phrase.strip().upper()
        if p in _DATE_PHRASES or re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
            out["date_phrase"] = p
    tod = raw.get("time_of_day")
    if isinstance(tod, str) and tod.upper() in _TODS:
        out["time_of_day"] = tod.upper()
    index = raw.get("option_index")
    if isinstance(index, int) and not isinstance(index, bool) and 1 <= index <= 9:
        out["option_index"] = index
    yes_no = raw.get("yes_no")
    if isinstance(yes_no, str) and yes_no.upper() in ("YES", "NO"):
        out["yes_no"] = yes_no.upper()
    return out


# Deliberately excludes words like "book": "I want to book a different time" must not confirm.
_YES = {"yes", "yeah", "ok", "okay", "confirm", "sure", "avunu", "sare", "sarey", "avnu",
        "అవును", "సరే", "ఓకే", "నిర్ధారించు"}
_NO = {"no", "nope", "dont", "don't", "kaadu", "kadu", "vaddu", "oddu", "కాదు", "వద్దు"}
_ORDINALS = {
    1: {"1", "one", "first", "okati", "modati", "modatidi", "ఒకటి", "మొదటి", "మొదటిది"},
    2: {"2", "two", "second", "rendu", "rendo", "rendodi", "రెండు", "రెండో", "రెండోది", "రెండవ"},
    3: {"3", "three", "third", "moodu", "moodo", "moododi", "మూడు", "మూడో", "మూడోది", "మూడవ"},
}
_OTHER_PERSON = ["mother", "father", "mom", "dad", "wife", "husband", "son", "daughter", "brother", "sister",
                 "grandmother", "grandfather", "someone else", "amma", "nanna", "bharya", "bharta", "koduku",
                 "kuthuru", "ammamma", "nanamma", "tatha", "అమ్మ", "నాన్న", "భార్య", "భర్త", "కొడుకు", "కూతురు",
                 "అమ్మమ్మ", "నానమ్మ", "తాత", "వేరే వాళ్ల"]
_SELF = ["for me", "myself", "for myself", "naaku", "naku", "na kosam", "naa kosam", "నాకు", "నా కోసం", "నాకే"]
_TODAY = ["today", "ee roju", "eeroju", "ivala", "ivvala", "ఈ రోజు", "ఈరోజు", "ఇవాళ", "ఇవ్వాళ"]
_TOMORROW = ["tomorrow", "repu", "రేపు"]
_DAY_AFTER = ["day after tomorrow", "ellundi", "ఎల్లుండి"]
_WEEKDAY_WORDS = {
    "MONDAY": ["monday", "somavaram", "సోమవారం"],
    "TUESDAY": ["tuesday", "mangalavaram", "మంగళవారం"],
    "WEDNESDAY": ["wednesday", "budhavaram", "బుధవారం"],
    "THURSDAY": ["thursday", "guruvaram", "గురువారం"],
    "FRIDAY": ["friday", "sukravaram", "shukravaram", "శుక్రవారం"],
    "SATURDAY": ["saturday", "sanivaram", "shanivaram", "శనివారం"],
    "SUNDAY": ["sunday", "adivaram", "aadivaram", "ఆదివారం"],
}
_TOD_WORDS = {
    "MORNING": ["morning", "udayam", "poddunna", "ఉదయం", "పొద్దున"],
    "AFTERNOON": ["afternoon", "madhyahnam", "madhyanam", "మధ్యాహ్నం"],
    "EVENING": ["evening", "sayantram", "sayantharam", "సాయంత్రం"],
}


def _has(text: str, words) -> bool:
    for w in words:
        if w.isascii():
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text):
                return True
        elif w in text:
            return True
    return False


def extract_rules(text: str, specialties: list[dict], localities: list[str]) -> dict:
    """Keyword extractor used when no language model is configured or when it fails.

    Understands simple English, Telugu script and common Latin-script Telugu words.
    """
    tnorm = normalize(text)
    out: dict = {}
    if not tnorm:
        return out
    tokens = set(tnorm.split())

    # A yes only counts in a short reply ("yes", "ok confirm"), never inside a longer sentence.
    if tokens & _NO:
        out["yes_no"] = "NO"
    elif tokens & _YES and len(tokens) <= 3:
        out["yes_no"] = "YES"
    if len(tokens) <= 3:
        for index, words in _ORDINALS.items():
            if tokens & words:
                out["option_index"] = index
                break

    if _has(tnorm, _OTHER_PERSON):
        out["for_whom"] = "OTHER"
    elif _has(tnorm, _SELF):
        out["for_whom"] = "SELF"

    for loc in localities:
        if normalize(loc) in tnorm:
            out["locality"] = loc
            break
    for sp in specialties:
        names = [normalize(sp["name_en"]), normalize(sp["name_te"]), sp["code"].lower().replace("_", " ")]
        if any(n and n in tnorm for n in names):
            out["specialty_code"] = sp["code"]
            break


    if _has(tnorm, _DAY_AFTER):
        out["date_phrase"] = "DAY_AFTER_TOMORROW"
    elif _has(tnorm, _TOMORROW):
        out["date_phrase"] = "TOMORROW"
    elif _has(tnorm, _TODAY):
        out["date_phrase"] = "TODAY"
    else:
        for day, words in _WEEKDAY_WORDS.items():
            if _has(tnorm, words):
                out["date_phrase"] = day
                break
    for tod, words in _TOD_WORDS.items():
        if _has(tnorm, words):
            out["time_of_day"] = tod
            break

    if _has(tnorm, ["reschedule", "postpone", "వాయిదా"]):
        out["intent"] = "RESCHEDULE"
    elif _has(tnorm, ["cancel", "raddu", "రద్దు"]):
        out["intent"] = "CANCEL_APPT"
    elif _has(tnorm, ["my appointments", "show appointments", "naa appointments"]):
        out["intent"] = "VIEW"

    # Anything longer than a bare yes/no or option pick may describe the concern.
    if "yes_no" not in out and "option_index" not in out and len(tnorm) > 2:
        out["concern_text"] = text.strip()[:300]
    return out


# ---------------------------------------------------------------- session data

def new_data(patient_id: str | None = None, patient_name: str | None = None) -> dict:
    return {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "concern_text": None,
        "specialty_id": None,
        "show_all_specialties": False,
        "locality": None,
        "date": None,
        "tod": None,
        "pref_done": False,
        "slot": None,
        "slot_options": [],
        "options": [],
        "unclear": 0,
        "emergency_ack": False,
    }


def _clear_search(data: dict) -> None:
    data["slot"] = None
    data["slot_options"] = []


def _specialty_name(sp: dict, lang: str) -> str:
    return sp["name_te"] if lang == "te" else sp["name_en"]


# ---------------------------------------------------------------- moves

def apply_move(data: dict, value: str, port) -> tuple[bool, str | None]:
    """Apply one canonical move (the value of a button). Returns (changed, action)."""
    kind, _, arg = value.partition(":")
    if kind == "patient":
        for p in port.authorized_patients():
            if p["id"] == arg:
                data["patient_id"], data["patient_name"] = p["id"], p["name"]
                _clear_search(data)
                return True, None
        return False, None
    if kind == "specialty":
        if any(sp["id"] == arg for sp in port.specialties()):
            data["specialty_id"] = arg
            data["show_all_specialties"] = False
            _clear_search(data)
            return True, None
        return False, None
    if kind == "other_specialty":
        data["specialty_id"] = None
        data["show_all_specialties"] = True
        _clear_search(data)
        return True, None
    if kind == "locality":
        if arg == ANY:
            data["locality"] = ANY
        else:
            match = next((loc for loc in port.localities() if loc.lower() == arg.lower()), None)
            if match is None:
                return False, None
            data["locality"] = match
        _clear_search(data)
        return True, None
    if kind == "pref":
        arg = arg.upper()
        if arg == ANY:
            data["date"], data["tod"] = None, None
        elif arg in ("TODAY", "TOMORROW"):
            data["date"] = arg  # resolved against the current date at search time
        elif arg in _TODS:
            data["tod"] = arg
        else:
            return False, None
        data["pref_done"] = True
        _clear_search(data)
        return True, None
    if kind == "slot":
        chosen = next((s for s in data.get("slot_options", []) if s["slot_id"] == arg), None)
        if chosen is None:
            return False, None  # only slots this server offered can be chosen
        data["slot"] = chosen
        return True, None
    if kind == "confirm":
        if arg == "yes" and data.get("slot"):
            return True, "BOOK"
        if arg == "no":
            data["slot"] = None
            return True, None
        return False, None
    if kind == "restart":
        keep_id, keep_name = (None, None) if port.is_caregiver else (data.get("patient_id"), data.get("patient_name"))
        ack = data.get("emergency_ack", False)
        data.clear()
        data.update(new_data(keep_id, keep_name))
        data["emergency_ack"] = ack
        return True, None
    if kind == "ack_not_emergency":
        data["emergency_ack"] = True
        return True, None
    return False, None


def apply_extraction(data: dict, ex: dict, state: str, port, today: date) -> tuple[bool, str | None, list[str]]:
    """Merge extracted fields into the session. Returns (changed, action, notes).

    `notes` are template keys to say before the next question.
    """
    changed, action, notes = False, None, []

    if state == ST_AWAITING_CONFIRMATION and ex.get("yes_no"):
        return (*apply_move(data, "confirm:yes" if ex["yes_no"] == "YES" else "confirm:no", port), notes)

    index = ex.get("option_index")
    options = data.get("options") or []
    if index and 1 <= index <= len(options):
        moved, action = apply_move(data, options[index - 1]["value"], port)
        return moved, action, notes

    if ex.get("intent") in ("CANCEL_APPT", "RESCHEDULE", "VIEW"):
        notes.append("other_intent")

    if ex.get("for_whom") == "OTHER":
        if port.is_caregiver:
            hint = normalize(ex.get("other_person_hint", ""))
            if hint and not data.get("patient_id"):
                for p in port.authorized_patients():
                    if hint in normalize(p["name"]) or normalize(p["name"]) in hint:
                        moved, _ = apply_move(data, f"patient:{p['id']}", port)
                        changed = changed or moved
                        break
        else:
            notes.append("other_person")

    code = ex.get("specialty_code")
    if code:
        sp = next((s for s in port.specialties() if s["code"].lower() == code.lower()), None)
        if sp and sp["id"] != data.get("specialty_id"):
            moved, _ = apply_move(data, f"specialty:{sp['id']}", port)
            changed = changed or moved

    locality = ex.get("locality")
    if locality:
        moved, _ = apply_move(data, f"locality:{locality}", port)
        changed = changed or moved

    phrase = ex.get("date_phrase")
    if phrase:
        resolved = resolve_date_phrase(phrase, today)
        if resolved is not None:
            data["date"] = resolved.isoformat()
            data["pref_done"] = True
            _clear_search(data)
            changed = True
    tod = ex.get("time_of_day")
    if tod:
        data["tod"] = tod
        data["pref_done"] = True
        _clear_search(data)
        changed = True

    concern = ex.get("concern_text")
    if concern and not data.get("specialty_id") and data.get("patient_id"):
        if state in (ST_UNDERSTANDING_REQUEST, ST_IDENTIFYING_SPECIALTY) or not data.get("concern_text"):
            data["concern_text"] = concern
            data["show_all_specialties"] = False
            changed = True

    if ex.get("yes_no") == "YES" and not changed and state != ST_AWAITING_CONFIRMATION:
        changed = True  # a plain "yes" to "shall we continue?" just moves on
    return changed, action, notes


# ---------------------------------------------------------------- prompts

def _opt(label: str, value: str) -> dict:
    return {"label": label, "value": value}


def _resolve_search_date(data: dict, today: date) -> date | None:
    raw = data.get("date")
    if not raw:
        return None
    if raw in ("TODAY", "TOMORROW"):
        return resolve_date_phrase(raw, today)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed >= today else None


def _slot_label(slot: dict, lang: str) -> str:
    when = slot["starts_at"]
    if isinstance(when, str):
        when = datetime.fromisoformat(when.replace("Z", "+00:00"))
    return t(lang, "slot_line", doctor=slot["doctor"], hospital=slot["hospital"], locality=slot["locality"],
             when=fmt_when(when, lang))


def confirmation_text(data: dict, lang: str, key: str = "confirm") -> str:
    slot = data["slot"]
    when = datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00"))
    return t(lang, key, patient=data.get("patient_name") or "", doctor=slot["doctor"], hospital=slot["hospital"],
             locality=slot["locality"], when=fmt_when(when, lang))


def next_prompt(data: dict, lang: str, port, today: date) -> tuple[str, str, list]:
    """Decide the next state from what is still missing. Returns (state, reply, options)."""
    restart = _opt(t(lang, "opt_restart"), "restart")

    if not data.get("patient_id"):
        patients = port.authorized_patients()
        if not patients:
            return ST_HANDOFF_REQUIRED, t(lang, "no_patients"), []
        if len(patients) == 1 and not port.is_caregiver:
            data["patient_id"], data["patient_name"] = patients[0]["id"], patients[0]["name"]
        else:
            return ST_IDENTIFYING_PATIENT, t(lang, "ask_patient"), [_opt(p["name"], f"patient:{p['id']}") for p in patients]

    specialties = port.specialties()
    if not data.get("specialty_id"):
        all_options = [_opt(_specialty_name(sp, lang), f"specialty:{sp['id']}") for sp in specialties]
        if data.get("show_all_specialties"):
            return ST_IDENTIFYING_SPECIALTY, t(lang, "ask_specialty_list"), all_options
        if not data.get("concern_text"):
            return ST_UNDERSTANDING_REQUEST, t(lang, "ask_concern"), []
        suggestions = port.suggest(data["concern_text"])[:3]
        by_id = {sp["id"]: sp for sp in specialties}
        suggestions = [s for s in suggestions if s["specialty_id"] in by_id]
        if not suggestions:
            return ST_IDENTIFYING_SPECIALTY, t(lang, "ask_specialty_list"), all_options
        lines, options = [t(lang, "suggest_specialty")], []
        for s in suggestions:
            name = _specialty_name(by_id[s["specialty_id"]], lang)
            lines.append(f"{name}: {s['explanation_te'] if lang == 'te' else s['explanation_en']}")
            options.append(_opt(name, f"specialty:{s['specialty_id']}"))
        options.append(_opt(t(lang, "opt_other_specialty"), "other_specialty"))
        return ST_IDENTIFYING_SPECIALTY, "\n".join(lines), options

    if not data.get("locality"):
        options = [_opt(loc, f"locality:{loc}") for loc in port.localities()]
        options.append(_opt(t(lang, "opt_any_area"), f"locality:{ANY}"))
        return ST_COLLECTING_LOCATION, t(lang, "ask_locality"), options

    if not data.get("pref_done"):
        options = [
            _opt(t(lang, "opt_any_time"), f"pref:{ANY}"),
            _opt(t(lang, "opt_today"), "pref:TODAY"),
            _opt(t(lang, "opt_tomorrow"), "pref:TOMORROW"),
            _opt(t(lang, "opt_morning"), "pref:MORNING"),
            _opt(t(lang, "opt_evening"), "pref:EVENING"),
        ]
        return ST_COLLECTING_PREFERENCES, t(lang, "ask_pref"), options

    if data.get("slot"):
        options = [_opt(t(lang, "opt_confirm"), "confirm:yes"), _opt(t(lang, "opt_go_back"), "confirm:no")]
        return ST_AWAITING_CONFIRMATION, confirmation_text(data, lang), options

    locality = None if data["locality"] == ANY else data["locality"]
    found = port.search(data["specialty_id"], locality, _resolve_search_date(data, today), data.get("tod"))
    if not found:
        # Nothing matched: drop the narrowing preferences and ask again from the area.
        data["locality"], data["date"], data["tod"], data["pref_done"] = None, None, None, False
        _clear_search(data)
        options = [_opt(loc, f"locality:{loc}") for loc in port.localities()]
        options.append(_opt(t(lang, "opt_any_area"), f"locality:{ANY}"))
        options.append(_opt(t(lang, "opt_other_specialty"), "other_specialty"))
        return ST_COLLECTING_LOCATION, t(lang, "no_slots") + " " + t(lang, "ask_locality"), options
    stored = []
    for s in found[:3]:
        starts = s["starts_at"]
        stored.append({
            "slot_id": str(s["slot_id"]),
            "doctor": s["doctor"],
            "hospital": s["hospital"],
            "locality": s["locality"],
            "starts_at": starts if isinstance(starts, str) else starts.isoformat(),
        })
    data["slot_options"] = stored
    options = [_opt(_slot_label(s, lang), f"slot:{s['slot_id']}") for s in stored] + [restart]
    return ST_SHOWING_AVAILABLE_SLOTS, t(lang, "show_slots"), options


def step(data: dict, lang: str, state: str, port, today: date, *, move: str | None = None, ex: dict | None = None) -> Result:
    """Advance the conversation by one user turn. Mutates `data`."""
    notes: list[str] = []
    if move:
        changed, action = apply_move(data, move, port)
        if move == "confirm:no" and changed:
            notes.append("declined")
    else:
        changed, action, notes = apply_extraction(data, ex or {}, state, port, today)
        if state == ST_AWAITING_CONFIRMATION and (ex or {}).get("yes_no") == "NO" and changed:
            notes.append("declined")

    if action == "BOOK":
        return Result(state=ST_AWAITING_CONFIRMATION, reply="", action="BOOK")

    if changed or notes:
        data["unclear"] = 0
    else:
        data["unclear"] = int(data.get("unclear", 0)) + 1
        if data["unclear"] >= MAX_UNCLEAR_TURNS:
            data["options"] = []
            return Result(state=ST_HANDOFF_REQUIRED, reply=t(lang, "handoff"))
        notes.append("unclear")

    new_state, reply, options = next_prompt(data, lang, port, today)
    data["options"] = options
    prefix = " ".join(t(lang, n) for n in notes)
    return Result(state=new_state, reply=(prefix + " " + reply).strip(), options=options)
