import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Airline(Base):
    __tablename__ = "airlines"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))


class Flight(Base):
    __tablename__ = "flights"
    __table_args__ = (
        CheckConstraint("total_seats > 0", name="positive_total_seats"),
        CheckConstraint("available_seats BETWEEN 0 AND total_seats", name="valid_available_seats"),
        CheckConstraint("price > 0", name="positive_price"),
        CheckConstraint("arrival_time > departure_time", name="valid_flight_times"),
        CheckConstraint("origin ~ '^[A-Z]{3}$'", name="valid_origin"),
        CheckConstraint("destination ~ '^[A-Z]{3}$'", name="valid_destination"),
        CheckConstraint("origin <> destination", name="different_airports"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="valid_currency"),
        CheckConstraint(
            "status IN ('SCHEDULED', 'DEPARTED', 'CANCELLED', 'COMPLETED')",
            name="valid_flight_status",
        ),
        Index(
            "uq_flight_number_departure_date",
            "flight_number",
            text("((departure_time AT TIME ZONE 'UTC')::date)"),
            unique=True,
        ),
        Index("ix_flights_search", "origin", "destination", "departure_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    flight_number: Mapped[str] = mapped_column(String(12))
    airline_code: Mapped[str] = mapped_column(ForeignKey("airlines.code"))
    airline: Mapped[Airline] = relationship(lazy="joined")
    origin: Mapped[str] = mapped_column(String(3))
    destination: Mapped[str] = mapped_column(String(3))
    departure_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrival_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total_seats: Mapped[int] = mapped_column(Integer)
    available_seats: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    status: Mapped[str] = mapped_column(String(12), default="SCHEDULED")


class SeatReservation(Base):
    __tablename__ = "seat_reservations"
    __table_args__ = (
        CheckConstraint("seat_count > 0", name="positive_reservation_seats"),
        CheckConstraint(
            "status IN ('ACTIVE', 'RELEASED', 'EXPIRED')", name="valid_reservation_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    flight_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flights.id"), index=True)
    booking_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    seat_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReservationCancellation(Base):
    __tablename__ = "reservation_cancellations"

    booking_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CacheRevision(Base):
    __tablename__ = "cache_revision"
    __table_args__ = (CheckConstraint("id = 1", name="single_cache_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(BigInteger, default=0)
