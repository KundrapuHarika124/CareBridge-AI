from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.constants import SLOT_AVAILABLE
from app.core.timeutil import utcnow
from app.models import Affiliation, AppointmentSlot


def test_affiliation_rejects_department_from_another_hospital(db, world):
    h1 = world["h1"]
    h2 = world["h2"]

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(
                Affiliation(
                    doctor_id=h1["doctor"].id,
                    hospital_id=h2["hospital"].id,
                    department_id=h1["dept"].id,
                    specialty_id=world["specialty_ortho"].id,
                )
            )
            db.flush()


def test_affiliation_allows_valid_and_multi_hospital_links(db, world):
    h1 = world["h1"]
    h2 = world["h2"]

    second = Affiliation(
        doctor_id=h1["doctor"].id,
        hospital_id=h2["hospital"].id,
        department_id=h2["dept"].id,
        specialty_id=world["specialty_ortho"].id,
    )
    db.add(second)
    db.commit()

    assert second.doctor_id == h1["doctor"].id
    assert second.hospital_id == h2["hospital"].id
    assert second.department_id == h2["dept"].id


def test_slot_rejects_doctor_different_from_affiliation(db, world):
    aff = world["h1"]["aff"]
    other_doctor = world["h2"]["doctor"]
    start = (utcnow() + timedelta(hours=48)).replace(second=0, microsecond=0)

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(
                AppointmentSlot(
                    affiliation_id=aff.id,
                    doctor_id=other_doctor.id,
                    starts_at=start,
                    ends_at=start + timedelta(minutes=20),
                    status=SLOT_AVAILABLE,
                )
            )
            db.flush()


def test_slot_allows_matching_affiliation_doctor(db, world):
    aff = world["h1"]["aff"]
    start = (utcnow() + timedelta(hours=72)).replace(second=0, microsecond=0)

    slot = AppointmentSlot(
        affiliation_id=aff.id,
        doctor_id=aff.doctor_id,
        starts_at=start,
        ends_at=start + timedelta(minutes=20),
        status=SLOT_AVAILABLE,
    )
    db.add(slot)
    db.commit()

    assert slot.affiliation_id == aff.id
    assert slot.doctor_id == aff.doctor_id
