"""Add password reset tokens.

Revision ID: 0004_password_reset
Revises: 0003_affiliation_integrity
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_password_reset"
down_revision = "0003_affiliation_integrity"
branch_labels = None
depends_on = None


def _validate_existing_password_reset_table(inspector) -> None:
    columns = {
        column["name"]: column
        for column in inspector.get_columns("password_reset_tokens", schema="public")
    }
    required = {
        "id",
        "user_id",
        "token_hash",
        "expires_at",
        "used_at",
        "created_at",
    }
    missing = required - set(columns)
    if missing:
        raise RuntimeError(
            "Migration 0004 cannot continue: password_reset_tokens is incomplete; "
            f"missing columns: {', '.join(sorted(missing))}"
        )

    wrong_types = []
    if not isinstance(columns["id"]["type"], sa.Uuid):
        wrong_types.append("id")
    if not isinstance(columns["user_id"]["type"], sa.Uuid):
        wrong_types.append("user_id")
    token_type = columns["token_hash"]["type"]
    if not isinstance(token_type, sa.String) or token_type.length != 64:
        wrong_types.append("token_hash")
    for name in ("expires_at", "used_at", "created_at"):
        column_type = columns[name]["type"]
        if not isinstance(column_type, sa.DateTime) or not getattr(column_type, "timezone", False):
            wrong_types.append(name)
    if wrong_types:
        raise RuntimeError(
            "Migration 0004 cannot continue: password_reset_tokens has incompatible "
            f"column types: {', '.join(sorted(wrong_types))}"
        )

    required_not_null = {
        "id": False,
        "user_id": False,
        "token_hash": False,
        "expires_at": False,
        "used_at": True,
        "created_at": False,
    }
    wrong_nullability = [
        name
        for name, expected_nullable in required_not_null.items()
        if bool(columns[name]["nullable"]) != expected_nullable
    ]
    if wrong_nullability:
        raise RuntimeError(
            "Migration 0004 cannot continue: password_reset_tokens has incompatible "
            f"nullability: {', '.join(sorted(wrong_nullability))}"
        )

    pk = inspector.get_pk_constraint("password_reset_tokens", schema="public")
    if pk.get("constrained_columns") != ["id"]:
        raise RuntimeError(
            "Migration 0004 cannot continue: password_reset_tokens "
            "must use id as its primary key"
        )

    indexes = {
        index["name"]
        for index in inspector.get_indexes("password_reset_tokens", schema="public")
    }
    foreign_keys = inspector.get_foreign_keys("password_reset_tokens", schema="public")
    if not any(
        fk["referred_table"] == "users"
        and fk["constrained_columns"] == ["user_id"]
        and fk["referred_columns"] == ["id"]
        and fk.get("ondelete") in (None, "NO ACTION")
        for fk in foreign_keys
    ):
        raise RuntimeError(
            "Migration 0004 cannot continue: password_reset_tokens.user_id "
            "is missing the required users.id foreign key with no cascading delete"
        )
    unique_constraints = inspector.get_unique_constraints(
        "password_reset_tokens",
        schema="public",
    )
    if not any(
        set(constraint["column_names"] or []) == {"token_hash"}
        for constraint in unique_constraints
    ):
        raise RuntimeError(
            "Migration 0004 cannot continue: password_reset_tokens.token_hash "
            "is missing the required unique constraint"
        )
    if "ix_password_reset_tokens_user_id" not in indexes:
        raise RuntimeError(
            "Migration 0004 cannot continue: password_reset_tokens "
            "is missing ix_password_reset_tokens_user_id"
        )
    if "ix_password_reset_tokens_expires_at" not in indexes:
        raise RuntimeError(
            "Migration 0004 cannot continue: password_reset_tokens "
            "is missing ix_password_reset_tokens_expires_at"
        )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names(schema="public"))
    if "password_reset_tokens" in table_names:
        _validate_existing_password_reset_table(inspector)
        return
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id",
        "password_reset_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_tokens_expires_at",
        "password_reset_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_tokens_expires_at",
        table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_user_id",
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
