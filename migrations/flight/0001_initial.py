import sqlalchemy as sa
from alembic import op

revision = "flight_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "airlines",
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "cache_revision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("id = 1", name="single_cache_revision"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "reservation_cancellations",
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("booking_id"),
    )
    op.create_table(
        "flights",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("flight_number", sa.String(length=12), nullable=False),
        sa.Column("airline_code", sa.String(length=3), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("departure_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_seats", sa.Integer(), nullable=False),
        sa.Column("available_seats", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="valid_currency"),
        sa.CheckConstraint("destination ~ '^[A-Z]{3}$'", name="valid_destination"),
        sa.CheckConstraint("origin ~ '^[A-Z]{3}$'", name="valid_origin"),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'DEPARTED', 'CANCELLED', 'COMPLETED')",
            name="valid_flight_status",
        ),
        sa.CheckConstraint("arrival_time > departure_time", name="valid_flight_times"),
        sa.CheckConstraint(
            "available_seats BETWEEN 0 AND total_seats", name="valid_available_seats"
        ),
        sa.CheckConstraint("origin <> destination", name="different_airports"),
        sa.CheckConstraint("price > 0", name="positive_price"),
        sa.CheckConstraint("total_seats > 0", name="positive_total_seats"),
        sa.ForeignKeyConstraint(
            ["airline_code"],
            ["airlines.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_flight_number_departure_date",
        "flights",
        ["flight_number", sa.literal_column("((departure_time AT TIME ZONE 'UTC')::date)")],
        unique=True,
    )
    op.create_index(
        "ix_flights_search", "flights", ["origin", "destination", "departure_time"], unique=False
    )
    op.create_table(
        "seat_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("flight_id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("seat_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'RELEASED', 'EXPIRED')", name="valid_reservation_status"
        ),
        sa.CheckConstraint("seat_count > 0", name="positive_reservation_seats"),
        sa.ForeignKeyConstraint(
            ["flight_id"],
            ["flights.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id"),
    )
    op.create_index(
        op.f("ix_seat_reservations_flight_id"), "seat_reservations", ["flight_id"], unique=False
    )
    op.execute("INSERT INTO cache_revision (id, revision) VALUES (1, 0)")


def downgrade():
    op.drop_table("seat_reservations")
    op.drop_table("flights")
    op.drop_table("reservation_cancellations")
    op.drop_table("cache_revision")
    op.drop_table("airlines")
