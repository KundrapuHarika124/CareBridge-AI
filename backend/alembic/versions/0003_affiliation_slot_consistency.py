"""Enforce affiliation, department and slot doctor consistency.

Revision ID: 0003_affiliation_integrity
Revises: 0002_add_hospital_location
Create Date: 2026-11-22

Adds composite foreign keys so:
- an affiliation department belongs to the affiliation hospital
- a slot doctor matches the affiliation doctor
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_affiliation_integrity"
down_revision = "0002_add_hospital_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    affiliation_mismatches = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM doctor_hospital_affiliations a
            JOIN departments d ON d.id = a.department_id
            WHERE d.hospital_id <> a.hospital_id
            """
        )
    ).scalar_one()
    if affiliation_mismatches:
        raise RuntimeError(
            f"Migration stopped: {affiliation_mismatches} affiliation(s) reference "
            "a department belonging to another hospital."
        )

    slot_mismatches = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM appointment_slots s
            JOIN doctor_hospital_affiliations a ON a.id = s.affiliation_id
            WHERE s.doctor_id <> a.doctor_id
            """
        )
    ).scalar_one()
    if slot_mismatches:
        raise RuntimeError(
            f"Migration stopped: {slot_mismatches} appointment slot(s) reference "
            "a doctor different from their affiliation."
        )

    department_unique_names = {
        item["name"]
        for item in inspector.get_unique_constraints("departments")
    }
    if "uq_departments_id_hospital" not in department_unique_names:
        op.create_unique_constraint(
            "uq_departments_id_hospital",
            "departments",
            ["id", "hospital_id"],
        )

    affiliation_unique_names = {
        item["name"]
        for item in inspector.get_unique_constraints("doctor_hospital_affiliations")
    }
    if "uq_affiliations_id_doctor" not in affiliation_unique_names:
        op.create_unique_constraint(
            "uq_affiliations_id_doctor",
            "doctor_hospital_affiliations",
            ["id", "doctor_id"],
        )

    affiliation_foreign_keys = {
        item["name"]
        for item in inspector.get_foreign_keys("doctor_hospital_affiliations")
    }
    if "fk_affiliation_department_hospital" not in affiliation_foreign_keys:
        op.create_foreign_key(
            "fk_affiliation_department_hospital",
            "doctor_hospital_affiliations",
            "departments",
            ["department_id", "hospital_id"],
            ["id", "hospital_id"],
        )

    slot_foreign_keys = {
        item["name"]
        for item in inspector.get_foreign_keys("appointment_slots")
    }
    if "fk_slot_affiliation_doctor" not in slot_foreign_keys:
        op.create_foreign_key(
            "fk_slot_affiliation_doctor",
            "appointment_slots",
            "doctor_hospital_affiliations",
            ["affiliation_id", "doctor_id"],
            ["id", "doctor_id"],
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_slot_affiliation_doctor",
        "appointment_slots",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_affiliation_department_hospital",
        "doctor_hospital_affiliations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_affiliations_id_doctor",
        "doctor_hospital_affiliations",
        type_="unique",
    )
    op.drop_constraint(
        "uq_departments_id_hospital",
        "departments",
        type_="unique",
    )
