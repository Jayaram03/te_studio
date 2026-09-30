"""rate history, package versions, change log, hotel options, templates, quotations

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30 05:30:00

Written to be safe to run on any database state: a column or table that already exists is left alone
(databases made by early versions get their missing tables from create_all first; see db.migrate).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

JSON = postgresql.JSONB(astext_type=sa.Text())

NEW_COLUMNS = {
    "source_documents": [sa.Column("changes", JSON, nullable=True)],
    "hotel_rates": [
        sa.Column("previous_rate_id", sa.Integer(), nullable=True),
        sa.Column("change_pct", sa.Numeric(7, 2), nullable=True),
        sa.Column("replaced_by_document_id", sa.Integer(), nullable=True),
        sa.Column("replaced_at", sa.DateTime(), nullable=True),
    ],
    "hotel_surcharges": [sa.Column("replaced_by_document_id", sa.Integer(), nullable=True)],
    "packages": [
        sa.Column("family_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("base_name", sa.String(300), nullable=True),
        sa.Column("edition", sa.String(100), nullable=True),
        sa.Column("previous_version_id", sa.Integer(), nullable=True),
        sa.Column("replaced_by_document_id", sa.Integer(), nullable=True),
        sa.Column("replaced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    ],
    "service_rates": [
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("previous_rate_id", sa.Integer(), nullable=True),
        sa.Column("change_pct", sa.Numeric(7, 2), nullable=True),
        sa.Column("replaced_by_document_id", sa.Integer(), nullable=True),
        sa.Column("replaced_at", sa.DateTime(), nullable=True),
    ],
    "trips": [
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("chosen_option", sa.String(60), nullable=True),
    ],
    "trip_items": [sa.Column("option_label", sa.String(60), nullable=True)],
}
NEW_INDEXES = [
    ("ix_hotel_rates_previous_rate_id", "hotel_rates", ["previous_rate_id"]),
    ("ix_packages_family_id", "packages", ["family_id"]),
    ("ix_service_rates_previous_rate_id", "service_rates", ["previous_rate_id"]),
    ("ix_trips_is_template", "trips", ["is_template"]),
]


def upgrade():
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for table, cols in NEW_COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        for col in cols:
            if col.name not in have:
                op.add_column(table, col)
    for name, table, cols in NEW_INDEXES:
        if name not in {i["name"] for i in insp.get_indexes(table)}:
            op.create_index(name, table, cols)
    # existing packages start their own family at version 1
    op.execute("update packages set family_id = id where family_id is null")

    if "quotations" not in tables:
        op.create_table(
            "quotations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("number", sa.String(30), nullable=True),
            sa.Column("trip_id", sa.Integer(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("customer_name", sa.String(200), nullable=True),
            sa.Column("customer_phone", sa.String(50), nullable=True),
            sa.Column("customer_email", sa.String(200), nullable=True),
            sa.Column("destination", sa.String(200), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("travellers", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("valid_until", sa.Date(), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("total", sa.Numeric(12, 2), nullable=True),
            sa.Column("per_person", sa.Numeric(12, 2), nullable=True),
            sa.Column("options", JSON, nullable=True),
            sa.Column("snapshot", JSON, nullable=False),
            sa.Column("share_token", sa.String(64), nullable=True),
            sa.Column("share_prices", sa.Boolean(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_quotations_number", "quotations", ["number"], unique=True)
        op.create_index("ix_quotations_trip_id", "quotations", ["trip_id"])
        op.create_index("ix_quotations_customer_name", "quotations", ["customer_name"])
        op.create_index("ix_quotations_status", "quotations", ["status"])
        op.create_index("ix_quotations_share_token", "quotations", ["share_token"], unique=True)
        op.create_index("ix_quotations_created_at", "quotations", ["created_at"])


def downgrade():
    op.drop_table("quotations")
    for name, table, _ in NEW_INDEXES:
        op.drop_index(name, table_name=table)
    for table, cols in NEW_COLUMNS.items():
        for col in cols:
            op.drop_column(table, col.name)
