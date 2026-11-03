import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("seat_count > 0", name="positive_booking_seats"),
        CheckConstraint("total_price > 0", name="positive_booking_price"),
        CheckConstraint("status IN ('CONFIRMED', 'CANCELLED')", name="valid_booking_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="valid_booking_currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    flight_id: Mapped[uuid.UUID]
    passenger_name: Mapped[str] = mapped_column(String(200))
    passenger_email: Mapped[str] = mapped_column(String(254))
    seat_count: Mapped[int] = mapped_column(Integer)
    total_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(12), default="CONFIRMED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BookingOperation(Base):
    __tablename__ = "booking_operations"
    __table_args__ = (
        CheckConstraint("kind IN ('CREATE', 'CANCEL')", name="valid_operation_kind"),
        CheckConstraint("state IN ('PENDING', 'DONE')", name="valid_operation_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(6))
    state: Mapped[str] = mapped_column(String(7), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
