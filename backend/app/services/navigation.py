"""Specialty navigation from the curated mapping table. Suggests where to go, never a diagnosis."""
import uuid
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Specialty, SpecialtyMapping
from app.serializers import specialty_out
from app.services import safety


FALLBACK_SYMPTOM_SPECIALTIES = (
    ("ORTHOPAEDICS", ("knee pain", "joint pain", "back pain", "shoulder pain", "leg pain", "neck pain",
                      "mokali noppi", "mokalu noppi", "keella noppi", "మోకాలి నొప్పి", "కీళ్ల నొప్పి")),
    ("DERMATOLOGY", ("skin rash", "rash", "itching", "pimples", "acne", "daddurllu", "దురద")),
    ("DENTISTRY", ("tooth pain", "toothache", "dental pain", "teeth pain", "gum pain", "పంటి నొప్పి", "దంత నొప్పి")),
    ("OPHTHALMOLOGY", ("eye discomfort", "eye pain", "blurred vision", "vision problem", "కంటి నొప్పి", "చూపు")),
)


def fallback_specialty_codes(text: str) -> list[str]:
    """Conservative offline fallback used only when seeded DB mappings find no match."""
    normalized = safety.normalize(text)
    if not normalized:
        return []
    matched = []
    for code, phrases in FALLBACK_SYMPTOM_SPECIALTIES:
        if any(safety._contains(normalized, phrase) for phrase in phrases):
            matched.append(code)
    return matched


def _latest_mappings(db: Session) -> list[SpecialtyMapping]:
    rows = db.scalars(select(SpecialtyMapping).order_by(SpecialtyMapping.concern_key, SpecialtyMapping.version.desc()))
    latest: dict[tuple, SpecialtyMapping] = {}
    for row in rows:
        latest.setdefault((row.concern_key, row.specialty_id), row)
    return list(latest.values())


def concerns(db: Session) -> list[dict]:
    seen: dict[str, dict] = {}
    for m in _latest_mappings(db):
        seen.setdefault(m.concern_key, {"concern_key": m.concern_key, "label_en": m.label_en, "label_te": m.label_te})
    return sorted(seen.values(), key=lambda c: c["label_en"])


def _suggestion(m: SpecialtyMapping) -> dict:
    return {
        "specialty": specialty_out(m.specialty),
        "concern_key": m.concern_key,
        "explanation_en": m.explanation_en,
        "explanation_te": m.explanation_te,
        "review_status": m.review_status,
        "mapping_version": m.version,
    }


def suggest(db: Session, *, text: str | None = None, concern_key: str | None = None, limit: int = 3) -> dict:
    """Possible specialties for a concern. Several may be returned; the user always chooses."""
    mappings = _latest_mappings(db)
    emergency = bool(text) and safety.is_emergency(text)
    if concern_key:
        matched = [m for m in mappings if m.concern_key == concern_key]
    elif text:
        by_id = {m.id: m for m in mappings}
        dicts = [{"id": m.id, "phrases": m.phrases} for m in mappings]
        matched = [by_id[d["id"]] for d in safety.match_concerns(text, dicts)]
        if not matched:
            for code in fallback_specialty_codes(text):
                specialty = db.scalar(
                    select(Specialty).where(Specialty.code == code)
                )
                if specialty is not None:
                    matched.append(SimpleNamespace(
                        specialty_id=specialty.id,
                        concern_key="symptom_fallback",
                        label_en="Symptom suggestion",
                        label_te="లక్షణ సూచన",
                        phrases=[],
                        explanation_en=(
                            f"{specialty.name_en} is a possible department to consider."
                        ),
                        explanation_te=(
                            f"{specialty.name_te} కలవాల్సిన విభాగంగా ఉండవచ్చు."
                        ),
                        review_status="DEMO_UNREVIEWED",
                        version=1,
                        specialty=specialty,
                    ))
    else:
        matched = []
        for code in fallback_specialty_codes(text or ""):
            specialty = db.scalar(select(Specialty).where(Specialty.code == code))
            if specialty is not None:
                matched.append(SimpleNamespace(
                    specialty_id=specialty.id,
                    concern_key="symptom_fallback",
                    label_en="Symptom suggestion",
                    label_te="Symptom suggestion",
                    phrases=[],
                    explanation_en=f"{specialty.name_en} is a possible department to consider.",
                    explanation_te=f"{specialty.name_te} is a possible department to consider.",
                    review_status="DEMO_UNREVIEWED",
                    version=1,
                    specialty=specialty,
                ))
    suggestions, seen = [], set()
    for m in matched:
        if m.specialty_id in seen:
            continue
        seen.add(m.specialty_id)
        suggestions.append(_suggestion(m))
        if len(suggestions) >= limit:
            break
    return {"emergency": emergency, "suggestions": suggestions}


def specialty_by_code(db: Session, code: str) -> Specialty | None:
    return db.scalar(select(Specialty).where(Specialty.code == code.strip().upper()))


def specialty_by_id(db: Session, specialty_id: uuid.UUID) -> Specialty | None:
    return db.get(Specialty, specialty_id)
