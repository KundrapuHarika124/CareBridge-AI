"""Create the synthetic demo data set.

    python -m scripts.seed            # add demo data to an empty database
    python -m scripts.seed --reset    # delete ALL application data first, then seed

Everything created here is fictional: three simulated hospitals, invented doctors and
patients. Run `alembic upgrade head` before this script.
"""
import argparse
import os
import sys
from datetime import time, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.constants import (
    CONSENT_TEXT_VERSION,
    PERM_BOOK_APPOINTMENTS,
    PERM_RECEIVE_REMINDERS,
    PERM_VIEW_APPOINTMENTS,
    REL_ACTIVE,
    REL_REQUESTED,
    REVIEW_DEMO_UNREVIEWED,
    ROLE_CAREGIVER,
    ROLE_DOCTOR,
    ROLE_HOSPITAL_ADMIN,
    ROLE_PATIENT,
    ROLE_SUPER_ADMIN,
)
from app.core.config import get_settings
from app.core.database import Base, SessionLocal
from app.core.security import hash_password
from app.core.timeutil import utcnow
from app.models import (
    Affiliation,
    CaregiverPermission,
    CareRelationship,
    ConsentRecord,
    Department,
    Doctor,
    DoctorSchedule,
    Hospital,
    HospitalStaff,
    Patient,
    Questionnaire,
    QuestionnaireResponse,
    Specialty,
    SpecialtyMapping,
    User,
)
from app.services import booking, directory

DEMO_PASSWORD = os.environ.get("SEED_PASSWORD", "Demo@12345")
SOURCE = "CareBridge demo seed. NOT clinically reviewed."

SPECIALTIES = [
    ("GENERAL_MEDICINE", "General Medicine", "సాధారణ వైద్యం"),
    ("ORTHOPAEDICS", "Orthopaedics", "ఎముకలు, కీళ్ల వైద్యం"),
    ("CARDIOLOGY", "Cardiology", "గుండె వైద్యం"),
    ("DERMATOLOGY", "Dermatology", "చర్మ వైద్యం"),
    ("ENT", "ENT (Ear, Nose, Throat)", "చెవి, ముక్కు, గొంతు వైద్యం"),
    ("PAEDIATRICS", "Paediatrics", "పిల్లల వైద్యం"),
    ("OPHTHALMOLOGY", "Ophthalmology", "కంటి వైద్యం"),
    ("GYNAECOLOGY", "Gynaecology", "స్త్రీల వైద్యం"),
    ("DENTISTRY", "Dentistry", "దంత వైద్యం"),
]

HOSPITALS = [
    ("A", "Simulated Hospital A", "Kukatpally",
     ["GENERAL_MEDICINE", "ORTHOPAEDICS", "CARDIOLOGY", "DERMATOLOGY", "ENT", "PAEDIATRICS", "DENTISTRY"]),
    ("B", "Simulated Hospital B", "Banjara Hills",
     ["GENERAL_MEDICINE", "ORTHOPAEDICS", "OPHTHALMOLOGY", "GYNAECOLOGY", "DERMATOLOGY", "CARDIOLOGY", "DENTISTRY"]),
    ("C", "Simulated Hospital C", "Secunderabad",
     ["GENERAL_MEDICINE", "ORTHOPAEDICS", "ENT", "OPHTHALMOLOGY", "PAEDIATRICS", "GYNAECOLOGY", "DENTISTRY"]),
]

DOCTOR_NAMES = [
    "Dr. Anitha R (Demo)", "Dr. Bhaskar V (Demo)", "Dr. Chaitanya K (Demo)", "Dr. Deepika M (Demo)",
    "Dr. Eswar P (Demo)", "Dr. Farida S (Demo)", "Dr. Gopal N (Demo)", "Dr. Harika T (Demo)",
    "Dr. Imran A (Demo)", "Dr. Jyothi B (Demo)", "Dr. Kiran D (Demo)", "Dr. Lalitha G (Demo)",
    "Dr. Mahesh C (Demo)", "Dr. Nandini J (Demo)", "Dr. Omkar L (Demo)", "Dr. Padma H (Demo)",
    "Dr. Qadir F (Demo)",
    "Dr. Ramesh S (Demo)", "Dr. Sravya P (Demo)", "Dr. Teja M (Demo)",
]

QUALIFICATIONS = {
    "GENERAL_MEDICINE": "MBBS, MD (General Medicine)", "ORTHOPAEDICS": "MBBS, MS (Orthopaedics)",
    "CARDIOLOGY": "MBBS, MD, DM (Cardiology)", "DERMATOLOGY": "MBBS, MD (Dermatology)",
    "ENT": "MBBS, MS (ENT)", "PAEDIATRICS": "MBBS, MD (Paediatrics)",
    "OPHTHALMOLOGY": "MBBS, MS (Ophthalmology)", "GYNAECOLOGY": "MBBS, MS (Obstetrics and Gynaecology)",
    "DENTISTRY": "BDS, MDS (Dentistry)",
}

# concern_key, label_en, label_te, specialty code, phrases, explanation_en, explanation_te
MAPPINGS = [
    ("joint_pain", "Knee, joint, back or bone pain", "మోకాలు, కీళ్లు, నడుము లేదా ఎముకల నొప్పి", "ORTHOPAEDICS",
     ["knee pain", "joint pain", "back pain", "shoulder pain", "leg pain", "neck pain", "fracture", "sprain",
      "mokali noppi", "mokalu noppi", "keella noppi", "nadumu noppi", "kaalu noppi",
      "మోకాలి నొప్పి", "మోకాళ్ల నొప్పి", "కీళ్ల నొప్పి", "నడుము నొప్పి", "కాలు నొప్పి", "భుజం నొప్పి", "మెడ నొప్పి"],
     "Orthopaedic doctors look after bones, joints and muscles.",
     "ఎముకలు, కీళ్లు, కండరాల సమస్యలను ఆర్థోపెడిక్ డాక్టర్లు చూస్తారు."),
    ("joint_pain", "Knee, joint, back or bone pain", "మోకాలు, కీళ్లు, నడుము లేదా ఎముకల నొప్పి", "GENERAL_MEDICINE",
     ["pain", "noppi", "నొప్పి"],
     "A general physician can see you first and guide you to the right doctor.",
     "సాధారణ వైద్యులు ముందుగా చూసి, సరైన డాక్టర్ వద్దకు పంపగలరు."),
    ("fever_cold", "Fever, cold, cough or weakness", "జ్వరం, జలుబు, దగ్గు లేదా నీరసం", "GENERAL_MEDICINE",
     ["fever", "cold", "cough", "body pains", "weakness", "tired", "headache", "vomiting", "loose motions", "stomach pain",
      "jwaram", "jalubu", "daggu", "neerasam", "tala noppi", "kadupu noppi",
      "జ్వరం", "జలుబు", "దగ్గు", "నీరసం", "తలనొప్పి", "తల నొప్పి", "వాంతులు", "కడుపు నొప్పి"],
     "General physicians see common illnesses such as fever, cough and stomach problems.",
     "జ్వరం, దగ్గు, కడుపు సమస్యల వంటి సాధారణ అనారోగ్యాలను సాధారణ వైద్యులు చూస్తారు."),
    ("skin", "Skin, hair or nail problem", "చర్మం, జుట్టు లేదా గోళ్ల సమస్య", "DERMATOLOGY",
     ["skin", "rash", "itching", "pimples", "acne", "hair fall", "allergy", "durada", "charma", "mottimalu",
      "చర్మ", "దురద", "మొటిమలు", "జుట్టు రాలడం", "దద్దుర్లు", "అలెర్జీ"],
     "Dermatologists look after skin, hair and nails.",
     "చర్మం, జుట్టు, గోళ్ల సమస్యలను చర్మ వైద్యులు చూస్తారు."),
    ("ear_nose_throat", "Ear, nose or throat problem", "చెవి, ముక్కు లేదా గొంతు సమస్య", "ENT",
     ["ear pain", "throat pain", "sore throat", "nose block", "sinus", "hearing", "tonsils",
      "chevi noppi", "gonthu noppi", "mukku", "చెవి నొప్పి", "గొంతు నొప్పి", "ముక్కు", "వినికిడి", "చెవి"],
     "ENT doctors look after the ear, nose and throat.",
     "చెవి, ముక్కు, గొంతు సమస్యలను ఈఎన్‌టీ డాక్టర్లు చూస్తారు."),
    ("eye", "Eye or vision problem", "కంటి లేదా చూపు సమస్య", "OPHTHALMOLOGY",
     ["eye", "eyes", "vision", "blurred", "spectacles", "glasses", "cataract", "kallu", "kanti", "choopu",
      "కళ్లు", "కంటి", "కన్ను", "చూపు", "కళ్లద్దాలు", "శుక్లం"],
     "Ophthalmologists look after eyes and vision.",
     "కళ్లు, చూపు సమస్యలను కంటి వైద్యులు చూస్తారు."),
    ("dental", "Tooth or dental pain", "పంటి లేదా దంత నొప్పి", "DENTISTRY",
     ["tooth pain", "toothache", "dental pain", "teeth pain", "gum pain", "pannu noppi", "పంటి నొప్పి", "దంత నొప్పి"],
     "Dentists look after teeth and gums.",
     "పంటలు, దంత సంబంధ సమస్యలను దంత వైద్యులు చూస్తారు."),
    ("heart_bp", "Blood pressure or heart check-up", "బీపీ లేదా గుండె పరీక్ష", "CARDIOLOGY",
     ["bp", "blood pressure", "heart checkup", "heart check up", "palpitations", "cholesterol", "gunde",
      "బీపీ", "రక్తపోటు", "గుండె", "కొలెస్ట్రాల్"],
     "Cardiologists look after the heart and blood pressure.",
     "గుండె, రక్తపోటు సమస్యలను గుండె వైద్యులు చూస్తారు."),
    ("child", "A child's health or vaccination", "పిల్లల ఆరోగ్యం లేదా టీకా", "PAEDIATRICS",
     ["child", "baby", "kid", "infant", "vaccination", "vaccine", "pillalu", "pillala", "papa ki", "babu ki",
      "పిల్లల", "పిల్లలు", "పాపకు", "బాబుకు", "టీకా"],
     "Paediatricians look after babies and children.",
     "శిశువులు, పిల్లల ఆరోగ్యాన్ని పిల్లల వైద్యులు చూస్తారు."),
    ("womens_health", "Pregnancy or women's health", "గర్భం లేదా స్త్రీల ఆరోగ్యం", "GYNAECOLOGY",
     ["pregnancy", "pregnant", "periods", "menstrual", "garbham", "nelasari", "గర్భం", "గర్భిణి", "నెలసరి"],
     "Gynaecologists look after pregnancy and women's health.",
     "గర్భం, స్త్రీల ఆరోగ్య సమస్యలను స్త్రీల వైద్యులు చూస్తారు."),
    ("general_checkup", "General check-up, sugar or thyroid", "సాధారణ పరీక్ష, షుగర్ లేదా థైరాయిడ్", "GENERAL_MEDICINE",
     ["checkup", "check up", "check-up", "health check", "sugar", "diabetes", "thyroid", "general",
      "షుగర్", "మధుమేహం", "థైరాయిడ్", "పరీక్ష", "చెకప్"],
     "A general physician is a good first doctor for check-ups and long-term conditions.",
     "సాధారణ పరీక్షలు, దీర్ఘకాలిక సమస్యలకు సాధారణ వైద్యులను ముందుగా కలవవచ్చు."),
]

QUESTIONS = [
    {"key": "main_concern", "text_en": "What is the main reason for this visit?",
     "text_te": "ఈ సందర్శనకు ప్రధాన కారణం ఏమిటి?"},
    {"key": "duration", "text_en": "How long has this been going on?", "text_te": "ఇది ఎంతకాలంగా ఉంది?"},
    {"key": "medicines", "text_en": "Are you taking any medicines now? Write the names as you know them.",
     "text_te": "ప్రస్తుతం ఏవైనా మందులు వాడుతున్నారా? మీకు తెలిసిన పేర్లు రాయండి."},
    {"key": "details", "text_en": "Is there anything else you want the doctor to know?",
     "text_te": "డాక్టర్‌కు ఇంకేమైనా చెప్పాలనుకుంటున్నారా?"},
    {"key": "questions", "text_en": "What questions do you have for the doctor?",
     "text_te": "డాక్టర్‌ను ఏమి అడగాలనుకుంటున్నారు?"},
]


def _user(db, name, role, *, email=None, phone=None, lang="en", pw_hash=None) -> User:
    user = User(full_name=name, role=role, email=email, phone=phone, preferred_language=lang, password_hash=pw_hash)
    db.add(user)
    db.flush()
    return user


def reset(db) -> None:
    """Delete every row of every application table (children before parents)."""
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()


def seed(db) -> dict:
    if db.scalar(select(Hospital.id).limit(1)) is not None:
        raise SystemExit("The database already has data. Use --reset to replace it.")
    pw_hash = hash_password(DEMO_PASSWORD)  # one hash reused: these are throwaway demo accounts
    db.add(_user(
        db,
        "Super Admin (Demo)",
        ROLE_SUPER_ADMIN,
        email="superadmin@carebridge.demo",
        pw_hash=pw_hash,
    ))

    specialties = {}
    for code, name_en, name_te in SPECIALTIES:
        specialties[code] = Specialty(code=code, name_en=name_en, name_te=name_te)
        db.add(specialties[code])
    db.flush()

    for key, label_en, label_te, code, phrases, expl_en, expl_te in MAPPINGS:
        db.add(SpecialtyMapping(
            specialty_id=specialties[code].id, concern_key=key, label_en=label_en, label_te=label_te, phrases=phrases,
            explanation_en=expl_en, explanation_te=expl_te, version=1, review_status=REVIEW_DEMO_UNREVIEWED, source=SOURCE,
        ))
    db.add(Questionnaire(
        specialty_id=None, version=1, title_en="Before your visit", title_te="మీ సందర్శనకు ముందు",
        questions=QUESTIONS, review_status=REVIEW_DEMO_UNREVIEWED,
    ))

    names = iter(DOCTOR_NAMES)
    doctor_number = 0
    shared_ortho = None
    affiliations = []
    hospitals = {}
    # Hyderabad localities with approximate coordinates for demo
    LOCATION_COORDS = {
        "A": (17.3850, 78.4867),  # Kukatpally - approximate Hyderabad center
        "B": (17.3610, 78.4730),  # Banjara Hills
        "C": (17.0377, 78.4729),  # Secunderabad
    }

    names = iter(DOCTOR_NAMES)
    doctor_number = 0
    shared_ortho = None
    affiliations = []
    hospitals = {}
    for letter, name, locality, codes in HOSPITALS:
        lat, lon = LOCATION_COORDS.get(letter, (17.0, 78.0))
        hospital = Hospital(
            name=name, locality=locality, city="Hyderabad", address=f"Demo address in {locality}. Not a real hospital.",
            phone=f"000-DEMO-{letter}", is_simulated=True, is_approved=True,
            latitude=lat, longitude=lon, approved_at=utcnow()
        )
        db.add(hospital)
        db.flush()
        hospitals[letter] = hospital
        admin = _user(db, f"Admin {letter} (Demo)", ROLE_HOSPITAL_ADMIN, email=f"admin.{letter.lower()}@carebridge.demo",
                      pw_hash=pw_hash)
        db.add(HospitalStaff(user_id=admin.id, hospital_id=hospital.id))
        for index, code in enumerate(codes):
            dept = Department(hospital_id=hospital.id, name=specialties[code].name_en)
            db.add(dept)
            db.flush()
            # One synthetic orthopaedic doctor works at both A and B, on alternate days.
            if letter == "B" and code == "ORTHOPAEDICS":
                doctor, weekdays = shared_ortho, (1, 3, 5)
            else:
                doctor_number += 1
                account = _user(db, next(names), ROLE_DOCTOR, email=f"doctor{doctor_number}@carebridge.demo", pw_hash=pw_hash)
                doctor = Doctor(user_id=account.id, qualifications=QUALIFICATIONS[code],
                                years_experience=5 + (doctor_number * 3) % 20, verification_status="SYNTHETIC")
                db.add(doctor)
                db.flush()
                weekdays = (0, 1, 2, 3, 4, 5)
                if letter == "A" and code == "ORTHOPAEDICS":
                    shared_ortho, weekdays = doctor, (0, 2, 4)
            aff = Affiliation(doctor_id=doctor.id, hospital_id=hospital.id, department_id=dept.id,
                              specialty_id=specialties[code].id, consultation_fee=Decimal(300 + 100 * (index % 4)))
            db.add(aff)
            db.flush()
            start, end = (time(10, 0), time(13, 0)) if index % 2 == 0 else (time(16, 0), time(19, 0))
            for weekday in weekdays:
                db.add(DoctorSchedule(affiliation_id=aff.id, weekday=weekday, start_time=start, end_time=end, slot_minutes=20))
            db.flush()
            affiliations.append(aff)

    slot_count = sum(directory.generate_slots(db, aff, days=14) for aff in affiliations)

    lakshmi = _user(db, "Lakshmi Devi (Demo)", ROLE_PATIENT, phone="9000000001", lang="te", pw_hash=pw_hash)
    ramesh = _user(db, "Ramesh Kumar (Demo)", ROLE_PATIENT, email="patient2@carebridge.demo", pw_hash=pw_hash)
    sita = _user(db, "Sita Devi (Demo)", ROLE_CAREGIVER, email="caregiver@carebridge.demo", pw_hash=pw_hash)
    p_lakshmi, p_ramesh = Patient(user_id=lakshmi.id), Patient(user_id=ramesh.id)
    db.add_all([p_lakshmi, p_ramesh])
    db.flush()

    granted = [PERM_VIEW_APPOINTMENTS, PERM_BOOK_APPOINTMENTS, PERM_RECEIVE_REMINDERS]
    active = CareRelationship(caregiver_user_id=sita.id, patient_id=p_lakshmi.id, status=REL_ACTIVE,
                              requested_permissions=granted, decided_at=utcnow())
    pending = CareRelationship(caregiver_user_id=sita.id, patient_id=p_ramesh.id, status=REL_REQUESTED,
                               requested_permissions=[PERM_VIEW_APPOINTMENTS])
    db.add_all([active, pending])
    db.flush()
    for permission in granted:
        db.add(CaregiverPermission(relationship_id=active.id, permission=permission))
    for rel, actor, action, perms in (
        (active, sita, "REQUESTED", granted), (active, lakshmi, "GRANTED", granted),
        (pending, sita, "REQUESTED", [PERM_VIEW_APPOINTMENTS]),
    ):
        db.add(ConsentRecord(relationship_id=rel.id, actor_user_id=actor.id, action=action,
                             permissions_snapshot=sorted(perms), consent_text_version=CONSENT_TEXT_VERSION))
    db.commit()

    # One existing appointment with intake answers, so the doctor dashboard is not empty.
    first_aff = affiliations[0]
    candidates = directory.available_slots(db, first_aff.id, start=utcnow() + timedelta(hours=1), limit=3)
    if candidates:
        appt = booking.book(db, actor=lakshmi, patient=p_lakshmi, slot_id=candidates[0].id,
                            reason="Fever and cough for three days (demo)", idempotency_key="seed-appointment-1")
        questionnaire = db.scalar(select(Questionnaire))
        db.add(QuestionnaireResponse(
            appointment_id=appt.id, questionnaire_id=questionnaire.id, submitted_by_user_id=lakshmi.id,
            answers={"main_concern": "Fever and cough (demo answer)", "duration": "Three days",
                     "questions": "Do I need any tests?"},
        ))
        db.commit()
    return {"hospitals": len(hospitals), "doctor_affiliations": len(affiliations), "doctors": doctor_number,
            "slots": slot_count}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed CareBridge AI with synthetic demo data.")
    parser.add_argument("--reset", action="store_true", help="delete all existing application data first")
    parser.add_argument("--allow-production", action="store_true", help="required to run when APP_ENV=production")
    args = parser.parse_args()
    if get_settings().is_production and not args.allow_production:
        sys.exit("Refusing to seed demo data with APP_ENV=production. Pass --allow-production to override.")
    db = SessionLocal()
    try:
        if args.reset:
            reset(db)
        summary = seed(db)
    finally:
        db.close()
    print("Seeded synthetic demo data:", summary)
    print(f"All demo accounts use the password: {DEMO_PASSWORD}")
    print("  Super Admin: superadmin@carebridge.demo")
    print("  Patient   : 9000000001 (Telugu)  |  patient2@carebridge.demo")
    print("  Caregiver : caregiver@carebridge.demo")
    print("  Doctor    : doctor1@carebridge.demo ... doctor%d@carebridge.demo" % summary["doctors"])
    print("  Admin     : admin.a@carebridge.demo, admin.b@carebridge.demo, admin.c@carebridge.demo")


if __name__ == "__main__":
    main()
