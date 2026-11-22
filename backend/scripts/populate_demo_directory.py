from datetime import time
from decimal import Decimal

from sqlalchemy import select, func

from app.constants import ROLE_DOCTOR, ROLE_HOSPITAL_ADMIN
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.core.timeutil import utcnow
from app.models import (
    Affiliation, AppointmentSlot, Department, Doctor,
    DoctorSchedule, Hospital, HospitalStaff, Specialty, User,
)
from app.services import directory
from scripts.seed import (
    DEMO_PASSWORD, HOSPITALS, DOCTOR_NAMES, QUALIFICATIONS, _user,
)

LOCATION_COORDS = {
    "A": (17.3850, 78.4867),
    "B": (17.3610, 78.4730),
    "C": (17.0377, 78.4729),
}


def main():
    db = SessionLocal()

    try:
        # Never overwrite existing hospital-directory data.
        protected_models = [
            Hospital, Doctor, Affiliation, DoctorSchedule,
            AppointmentSlot, HospitalStaff, Department,
        ]
        for model in protected_models:
            count = db.scalar(select(func.count()).select_from(model))
            if count:
                raise RuntimeError(
                    f"{model.__tablename__} already contains {count} rows. "
                    "Stopping without changing anything."
                )

        specialties = {
            s.code: s for s in db.scalars(select(Specialty)).all()
        }
        required_codes = {
            code for _, _, _, codes in HOSPITALS for code in codes
        }
        missing = required_codes - specialties.keys()
        if missing:
            raise RuntimeError(f"Missing specialties: {sorted(missing)}")

        doctor_count = sum(len(codes) for _, _, _, codes in HOSPITALS) - 1
        emails = (
            [f"admin.{letter.lower()}@carebridge.demo"
             for letter, _, _, _ in HOSPITALS]
            + [f"doctor{i}@carebridge.demo"
               for i in range(1, doctor_count + 1)]
        )
        collisions = db.scalars(
            select(User.email).where(User.email.in_(emails))
        ).all()
        if collisions:
            raise RuntimeError(
                f"Demo email addresses already exist: {collisions}"
            )

        pw_hash = hash_password(DEMO_PASSWORD)
        names = iter(DOCTOR_NAMES)
        doctor_number = 0
        shared_ortho = None
        affiliations = []
        hospital_count = 0

        for letter, name, locality, codes in HOSPITALS:
            lat, lon = LOCATION_COORDS[letter]
            hospital = Hospital(
                name=name,
                locality=locality,
                city="Hyderabad",
                address=f"Demo address in {locality}. Not a real hospital.",
                phone=f"000-DEMO-{letter}",
                is_simulated=True,
                is_approved=True,
                latitude=lat,
                longitude=lon,
                approved_at=utcnow(),
            )
            db.add(hospital)
            db.flush()
            hospital_count += 1

            admin = _user(
                db,
                f"Admin {letter} (Demo)",
                ROLE_HOSPITAL_ADMIN,
                email=f"admin.{letter.lower()}@carebridge.demo",
                pw_hash=pw_hash,
            )
            db.add(HospitalStaff(user_id=admin.id, hospital_id=hospital.id))

            for index, code in enumerate(codes):
                dept = Department(
                    hospital_id=hospital.id,
                    name=specialties[code].name_en,
                )
                db.add(dept)
                db.flush()

                if letter == "B" and code == "ORTHOPAEDICS":
                    doctor = shared_ortho
                    weekdays = (1, 3, 5)
                else:
                    doctor_number += 1
                    try:
                        doctor_name = next(names)
                    except StopIteration:
                        doctor_name = f"Dr. CareBridge Demo {doctor_number:02d}"

                    account = _user(
                        db,
                        doctor_name,
                        ROLE_DOCTOR,
                        email=f"doctor{doctor_number}@carebridge.demo",
                        pw_hash=pw_hash,
                    )
                    doctor = Doctor(
                        user_id=account.id,
                        qualifications=QUALIFICATIONS[code],
                        years_experience=5 + (doctor_number * 3) % 20,
                        verification_status="SYNTHETIC",
                    )
                    db.add(doctor)
                    db.flush()

                    weekdays = (0, 1, 2, 3, 4, 5)
                    if letter == "A" and code == "ORTHOPAEDICS":
                        shared_ortho = doctor
                        weekdays = (0, 2, 4)

                aff = Affiliation(
                    doctor_id=doctor.id,
                    hospital_id=hospital.id,
                    department_id=dept.id,
                    specialty_id=specialties[code].id,
                    consultation_fee=Decimal(300 + 100 * (index % 4)),
                )
                db.add(aff)
                db.flush()

                start, end = (
                    (time(10, 0), time(13, 0))
                    if index % 2 == 0
                    else (time(16, 0), time(19, 0))
                )

                for weekday in weekdays:
                    db.add(DoctorSchedule(
                        affiliation_id=aff.id,
                        weekday=weekday,
                        start_time=start,
                        end_time=end,
                        slot_minutes=20,
                    ))

                affiliations.append(aff)

        db.flush()

        slot_count = 0
        for aff in affiliations:
            slot_count += directory.generate_slots(db, aff, days=14)
            db.flush()

        db.commit()

        print("Demo directory created successfully:")
        print("Hospitals:", hospital_count)
        print("Doctors:", doctor_number)
        print("Affiliations:", len(affiliations))
        print("Appointment slots:", slot_count)
        print("Existing patient account and specialty data preserved.")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
