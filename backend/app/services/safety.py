"""Text safety checks and concern matching. Pure functions: no database, no network.

IMPORTANT: the phrase lists below are DEMO content. They have NOT been reviewed by a
clinician and are deliberately broad. They must be reviewed and approved by qualified
healthcare professionals before any real use.
"""
import re
import unicodedata

EMERGENCY_REVIEW_STATUS = "DEMO_UNREVIEWED"

EMERGENCY_PHRASES = [
    # English
    "chest pain", "heart attack", "can't breathe", "cant breathe", "cannot breathe", "not able to breathe",
    "difficulty breathing", "trouble breathing", "unconscious", "not responding", "severe bleeding",
    "heavy bleeding", "stroke", "seizure", "fits", "poison", "overdose", "suicide", "kill myself",
    "accident", "emergency", "ambulance",
    # Telugu written in Latin letters
    "chaati noppi", "chathi noppi", "gunde noppi", "gunde potu", "gundepotu", "oopiri aadatam ledu",
    "oopiri adatam ledu", "oopiri andatam ledu", "spruha ledu", "pakshavatam",
    # Telugu script
    "ఛాతీ నొప్పి", "ఛాతి నొప్పి", "గుండె నొప్పి", "గుండెపోటు", "గుండె పోటు", "ఊపిరి ఆడటం లేదు",
    "ఊపిరి అందడం లేదు", "శ్వాస ఆడటం లేదు", "స్పృహ లేదు", "స్పృహ తప్పి", "రక్తస్రావం", "పక్షవాతం",
    "ఫిట్స్", "విషం", "ఆత్మహత్య", "ప్రమాదం", "ఎమర్జెన్సీ", "అత్యవసర", "అంబులెన్స్",
]

MEDICAL_ADVICE_PATTERNS = [
    r"\bwhat (medicine|tablet|drug|medication)\b", r"\bwhich (medicine|tablet|drug|medication)\b",
    r"\b(dose|dosage|how many mg|how much mg)\b", r"\bshould i (take|stop|increase|reduce)\b",
    r"\bcan i (take|stop)\b", r"\bprescri(be|ption)\b", r"\bdiagnos(e|is)\b",
    r"\bwhat (disease|illness|condition) (do i|is this)\b", r"\bwhat is wrong with me\b",
    r"\bis it (cancer|serious|dangerous)\b",
    r"\b(ye|e|em|emi) (mandu|tablet|medicine)\b", r"\bmandu (cheppu|cheppandi|ivvu|vesuko)", r"\btablet vesuko",
    r"ఏ మందు", r"ఏం మందు", r"మందు చెప్ప", r"మందు వేసుకో", r"డోస్", r"మోతాదు", r"ఏ వ్యాధి", r"ఏం జబ్బు",
]

_ADVICE_RE = re.compile("|".join(MEDICAL_ADVICE_PATTERNS), re.IGNORECASE)


def normalize(text: str) -> str:
    """Lowercase, normalize Unicode and collapse punctuation and whitespace."""
    text = unicodedata.normalize("NFC", text or "").lower().replace("\u2019", "'")
    text = re.sub(r"[.,!?;:()\[\]\"“”‘’]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains(haystack: str, phrase: str) -> bool:
    """Substring match; Latin-letter phrases must match whole words ("fits" is not in "benefits")."""
    if phrase.isascii():
        return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", haystack) is not None
    return phrase in haystack


def is_emergency(text: str) -> bool:
    t = normalize(text)
    return any(_contains(t, phrase) for phrase in EMERGENCY_PHRASES)


def asks_medical_advice(text: str) -> bool:
    return bool(_ADVICE_RE.search(normalize(text)))


def match_concerns(text: str, mappings: list[dict]) -> list[dict]:
    """Return the mappings whose phrases occur in `text`, best match first.

    `mappings` are dicts with at least "phrases" (list of str). A mapping scores by its
    longest matching phrase, so "knee pain" outranks a bare "pain".
    """
    t = normalize(text)
    if not t:
        return []
    scored = []
    for m in mappings:
        best = 0
        for phrase in m.get("phrases", []):
            p = normalize(phrase)
            if p and _contains(t, p):
                best = max(best, len(p))
        if best:
            scored.append((best, m))
    scored.sort(key=lambda item: -item[0])
    return [m for _, m in scored]
