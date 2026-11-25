"""Assistant reply templates in Telugu and English.

Every assistant reply is built from these templates and database values. The language
model never writes text that is shown to the user. Telugu wording should be reviewed by
a native speaker before real use.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_EN_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_TE_DAYS = ["సోమవారం", "మంగళవారం", "బుధవారం", "గురువారం", "శుక్రవారం", "శనివారం", "ఆదివారం"]
_TE_MONTHS = ["జనవరి", "ఫిబ్రవరి", "మార్చి", "ఏప్రిల్", "మే", "జూన్", "జూలై", "ఆగస్టు", "సెప్టెంబర్", "అక్టోబర్", "నవంబర్", "డిసెంబర్"]

T = {
    "en": {
        "greet": "Hello {name}. I can help you book a doctor's appointment.",
        "ask_patient": "Who is the appointment for?",
        "no_patients": "You do not have permission to book for any patient yet. Ask the patient to give you booking access.",
        "other_person": "From this account I can only book for you. To book for a family member, they need their own account and must give you caregiver access.",
        "ask_concern": "What is the visit about? Say it in your own words, for example 'knee pain'.",
        "suggest_specialty": "For this, people usually see the doctors below. This is only a suggestion to help you choose, not a diagnosis. Which would you like?",
        "ask_specialty_list": "I could not match that to a kind of doctor. Please choose one.",
        "ask_locality": "Which area is convenient for you?",
        "ask_pref": "When would you like to go?",
        "no_slots": "I could not find a free time for that. Let us try a different area or day.",
        "show_slots": "These are the earliest available times. Which one suits you?",
        "slot_line": "{doctor}, {hospital} ({locality}), {when}",
        "confirm": "Please check: {patient} with {doctor} at {hospital} ({locality}) on {when}. Shall I confirm this booking?",
        "booked": "Your appointment request for {patient} with {doctor} at {hospital} on {when} has been sent. It will be confirmed after the doctor approves it.",
        "slot_taken": "Sorry, that time was just taken.",
        "declined": "Okay, I have not booked it.",
        "unclear": "Sorry, I did not understand.",
        "handoff": "I am not able to help with this here. Please use the Book Appointment screen, or call the hospital.",
        "emergency": "This may need urgent care. Please call 112 or 108 now, or go to the nearest emergency department. I cannot book routine appointments for emergencies.",
        "medical_advice": "I can't advise on medicines or say what a condition is. A doctor can. I can help you book one.",
        "tap_confirm": "I may have misheard. Please tap Confirm to book, or Go back.",
        "expired": "This conversation timed out. Please start again.",
        "other_intent": "Here I can book appointments. To view, cancel or change one, open Appointments.",
        "cancelled": "Okay, stopped. You can start again any time.",
        "booking_failed": "I could not complete the booking. Nothing was booked.",
        "opt_any_area": "Any area",
        "opt_any_time": "Earliest available",
        "opt_today": "Today",
        "opt_tomorrow": "Tomorrow",
        "opt_morning": "Morning",
        "opt_afternoon": "Afternoon",
        "opt_evening": "Evening",
        "opt_confirm": "Confirm",
        "opt_go_back": "Go back",
        "opt_other_specialty": "Another kind of doctor",
        "opt_restart": "Start again",
        "opt_not_emergency": "This is not an emergency, continue",
    },
    "te": {
        "greet": "నమస్కారం {name}. డాక్టర్ అపాయింట్‌మెంట్ బుక్ చేయడంలో నేను సహాయం చేస్తాను.",
        "ask_patient": "అపాయింట్‌మెంట్ ఎవరి కోసం?",
        "no_patients": "మీకు ఇంకా ఏ పేషెంట్ కోసం బుక్ చేసే అనుమతి లేదు. బుకింగ్ అనుమతి ఇవ్వమని పేషెంట్‌ను అడగండి.",
        "other_person": "ఈ ఖాతా నుండి మీ కోసం మాత్రమే బుక్ చేయగలను. కుటుంబ సభ్యుల కోసం బుక్ చేయాలంటే వారికి సొంత ఖాతా ఉండి, మీకు సంరక్షకుడిగా అనుమతి ఇవ్వాలి.",
        "ask_concern": "డాక్టర్‌ను ఏ సమస్య కోసం కలవాలి? మీ మాటల్లో చెప్పండి, ఉదాహరణకు 'మోకాలి నొప్పి'.",
        "suggest_specialty": "ఈ సమస్యకు సాధారణంగా కింది డాక్టర్లను కలుస్తారు. ఇది ఎంచుకోవడానికి సూచన మాత్రమే, రోగ నిర్ధారణ కాదు. ఏది కావాలి?",
        "ask_specialty_list": "దీనికి సరిపోయే డాక్టర్ విభాగం దొరకలేదు. దయచేసి ఒకటి ఎంచుకోండి.",
        "ask_locality": "మీకు ఏ ప్రాంతం సౌకర్యంగా ఉంటుంది?",
        "ask_pref": "ఎప్పుడు వెళ్లాలనుకుంటున్నారు?",
        "no_slots": "దానికి ఖాళీ సమయం దొరకలేదు. వేరే ప్రాంతం లేదా రోజు ప్రయత్నిద్దాం.",
        "show_slots": "అందుబాటులో ఉన్న తొలి సమయాలు ఇవి. మీకు ఏది సరిపోతుంది?",
        "slot_line": "{doctor}, {hospital} ({locality}), {when}",
        "confirm": "దయచేసి సరిచూడండి: {patient} కోసం {doctor}, {hospital} ({locality}), {when}. ఈ బుకింగ్ నిర్ధారించమంటారా?",
        "booked": "{patient} కోసం {hospital}లో {doctor} వద్ద {when} సమయానికి అపాయింట్‌మెంట్ అభ్యర్థన పంపబడింది. డాక్టర్ ఆమోదించిన తర్వాత నిర్ధారించబడుతుంది.",
        "slot_taken": "క్షమించండి, ఆ సమయం ఇప్పుడే వేరొకరు తీసుకున్నారు.",
        "declined": "సరే, బుక్ చేయలేదు.",
        "unclear": "క్షమించండి, అర్థం కాలేదు.",
        "handoff": "ఇక్కడ దీనిలో సహాయం చేయలేకపోతున్నాను. దయచేసి 'అపాయింట్‌మెంట్ బుక్ చేయండి' స్క్రీన్ వాడండి, లేదా ఆసుపత్రికి ఫోన్ చేయండి.",
        "emergency": "దీనికి అత్యవసర వైద్యం అవసరం కావచ్చు. వెంటనే 112 లేదా 108కి ఫోన్ చేయండి, లేదా దగ్గరలోని అత్యవసర విభాగానికి వెళ్లండి. అత్యవసర పరిస్థితులకు సాధారణ అపాయింట్‌మెంట్ బుక్ చేయలేను.",
        "medical_advice": "మందులు లేదా వ్యాధి గురించి నేను సలహా ఇవ్వలేను. డాక్టర్ చెప్పగలరు. డాక్టర్ అపాయింట్‌మెంట్ బుక్ చేయడంలో సహాయం చేయగలను.",
        "tap_confirm": "నేను సరిగ్గా వినలేదేమో. బుక్ చేయడానికి 'నిర్ధారించు' నొక్కండి, లేదా 'వెనక్కి' నొక్కండి.",
        "expired": "ఈ సంభాషణ సమయం ముగిసింది. దయచేసి మళ్లీ మొదలుపెట్టండి.",
        "other_intent": "ఇక్కడ అపాయింట్‌మెంట్ బుక్ చేయగలను. చూడటానికి, రద్దు చేయడానికి లేదా మార్చడానికి 'అపాయింట్‌మెంట్లు' తెరవండి.",
        "cancelled": "సరే, ఆపేశాను. ఎప్పుడైనా మళ్లీ మొదలుపెట్టవచ్చు.",
        "booking_failed": "బుకింగ్ పూర్తి చేయలేకపోయాను. ఏదీ బుక్ కాలేదు.",
        "opt_any_area": "ఏ ప్రాంతమైనా",
        "opt_any_time": "తొలి అందుబాటు సమయం",
        "opt_today": "ఈ రోజు",
        "opt_tomorrow": "రేపు",
        "opt_morning": "ఉదయం",
        "opt_afternoon": "మధ్యాహ్నం",
        "opt_evening": "సాయంత్రం",
        "opt_confirm": "నిర్ధారించు",
        "opt_go_back": "వెనక్కి",
        "opt_other_specialty": "వేరే డాక్టర్ విభాగం",
        "opt_restart": "మళ్లీ మొదలుపెట్టు",
        "opt_not_emergency": "ఇది అత్యవసరం కాదు, కొనసాగించు",
    },
}


def t(lang: str, key: str, **kw) -> str:
    table = T.get(lang, T["en"])
    return table.get(key, T["en"][key]).format(**kw)


def fmt_when(dt: datetime, lang: str) -> str:
    """Human-readable appointment time in IST, e.g. 'Mon 23 Nov, 10:30 AM'."""
    local = dt.astimezone(IST)
    hour12 = local.hour % 12 or 12
    clock = f"{hour12}:{local.minute:02d}"
    if lang == "te":
        part = "ఉదయం" if local.hour < 12 else ("మధ్యాహ్నం" if local.hour < 16 else "సాయంత్రం")
        return f"{_TE_DAYS[local.weekday()]} {local.day} {_TE_MONTHS[local.month - 1]}, {part} {clock}"
    return f"{_EN_DAYS[local.weekday()]} {local.day} {_EN_MONTHS[local.month - 1]}, {clock} {'AM' if local.hour < 12 else 'PM'}"
