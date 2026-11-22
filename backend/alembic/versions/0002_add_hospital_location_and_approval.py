"""Add hospital location coordinates and approval status.

Revision ID: 0002_add_hospital_location
Revises: 0001_initial
Create Date: 2026-11-21

This migration adds:
- latitude/longitude for real geolocation-based hospital discovery
- is_approved/approved_at for Super Admin hospital onboarding
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_add_hospital_location"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("hospitals")}
    indexes = {index["name"] for index in inspector.get_indexes("hospitals")}

    if "latitude" not in columns:
        op.add_column("hospitals", sa.Column("latitude", sa.Float(), nullable=True))
    if "longitude" not in columns:
        op.add_column("hospitals", sa.Column("longitude", sa.Float(), nullable=True))
    if "is_approved" not in columns:
        op.add_column("hospitals", sa.Column("is_approved", sa.Boolean(), nullable=False, server_default="false"))
    if "approved_at" not in columns:
        op.add_column("hospitals", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))

    if "ix_hospitals_latitude" not in indexes:
        op.create_index("ix_hospitals_latitude", "hospitals", ["latitude"])
    if "ix_hospitals_longitude" not in indexes:
        op.create_index("ix_hospitals_longitude", "hospitals", ["longitude"])


def downgrade() -> None:
    op.drop_index("ix_hospitals_latitude", table_name="hospitals")
    op.drop_index("ix_hospitals_longitude", table_name="hospitals")
    op.drop_column("hospitals", "approved_at")
    op.drop_column("hospitals", "is_approved")
    op.drop_column("hospitals", "longitude")
    op.drop_column("hospitals", "latitude")