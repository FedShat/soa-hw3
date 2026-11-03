import sqlalchemy as sa
from alembic import op

revision = "booking_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "booking_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=6), nullable=False),
        sa.Column("state", sa.String(length=7), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('CREATE', 'CANCEL')", name="valid_operation_kind"),
        sa.CheckConstraint("state IN ('PENDING', 'DONE')", name="valid_operation_state"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_booking_operations_booking_id"), "booking_operations", ["booking_id"], unique=False
    )
    op.create_index(
        op.f("ix_booking_operations_state"), "booking_operations", ["state"], unique=False
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("flight_id", sa.Uuid(), nullable=False),
        sa.Column("passenger_name", sa.String(length=200), nullable=False),
        sa.Column("passenger_email", sa.String(length=254), nullable=False),
        sa.Column("seat_count", sa.Integer(), nullable=False),
        sa.Column("total_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="valid_booking_currency"),
        sa.CheckConstraint("status IN ('CONFIRMED', 'CANCELLED')", name="valid_booking_status"),
        sa.CheckConstraint("seat_count > 0", name="positive_booking_seats"),
        sa.CheckConstraint("total_price > 0", name="positive_booking_price"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bookings_user_id"), "bookings", ["user_id"], unique=False)


def downgrade():
    op.drop_table("bookings")
    op.drop_table("booking_operations")
