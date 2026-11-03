import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from services.booking.models import Booking, BookingOperation

logger = logging.getLogger(__name__)


class BookingService:
    def __init__(self, sessions, flights, recovery_interval=2):
        self.sessions = sessions
        self.flights = flights
        self.recovery_interval = recovery_interval

    async def operation(self, booking_id, kind):
        async with self.sessions.begin() as session:
            operation = BookingOperation(booking_id=booking_id, kind=kind)
            session.add(operation)
            await session.flush()
            return operation.id

    async def create(self, data):
        flight = await self.flights.get(data.flight_id)
        booking_id = uuid4()
        operation_id = await self.operation(booking_id, "CREATE")
        try:
            async with self.sessions.begin() as session:
                operation = await session.get(BookingOperation, operation_id, with_for_update=True)
                if operation.state != "PENDING":
                    raise HTTPException(503, "Booking attempt expired; please retry")
                await self.flights.reserve(data.flight_id, data.seat_count, booking_id)
                booking = Booking(
                    id=booking_id,
                    **data.model_dump(),
                    total_price=Decimal(flight.price) * data.seat_count,
                    currency=flight.currency,
                )
                session.add(booking)
                operation.state = "DONE"
                await session.flush()
            return booking
        except Exception:
            try:
                await self.recover_one(operation_id)
            except Exception:
                logger.exception("Booking compensation pending operation=%s", operation_id)
            raise

    async def get(self, booking_id):
        async with self.sessions() as session:
            booking = await session.get(Booking, booking_id)
            if booking is None:
                raise HTTPException(404, "Booking not found")
            return booking

    async def list(self, user_id):
        async with self.sessions() as session:
            return list(
                await session.scalars(
                    select(Booking)
                    .where(Booking.user_id == user_id)
                    .order_by(Booking.created_at.desc(), Booking.id)
                )
            )

    async def cancel(self, booking_id):
        booking = await self.get(booking_id)
        if booking.status != "CONFIRMED":
            raise HTTPException(409, "Booking is already cancelled")
        operation_id = await self.operation(booking_id, "CANCEL")
        async with self.sessions.begin() as session:
            operation = await session.get(BookingOperation, operation_id, with_for_update=True)
            booking = await session.get(Booking, booking_id, with_for_update=True)
            if booking.status == "CONFIRMED":
                await self.flights.release(booking_id)
                booking.status = "CANCELLED"
            operation.state = "DONE"
            await session.flush()
        return booking

    async def recover_one(self, operation_id):
        async with self.sessions.begin() as session:
            operation = await session.scalar(
                select(BookingOperation)
                .where(BookingOperation.id == operation_id, BookingOperation.state == "PENDING")
                .with_for_update(skip_locked=True)
            )
            if operation is None:
                return
            booking = await session.get(Booking, operation.booking_id, with_for_update=True)
            if operation.kind == "CREATE" and booking is None:
                await self.flights.release(operation.booking_id)
            elif operation.kind == "CANCEL" and booking and booking.status == "CONFIRMED":
                await self.flights.release(operation.booking_id)
                booking.status = "CANCELLED"
            operation.state = "DONE"
            logger.info("Booking operation recovered id=%s kind=%s", operation.id, operation.kind)

    async def recovery_loop(self):
        while True:
            await asyncio.sleep(self.recovery_interval)
            try:
                async with self.sessions() as session:
                    operations = list(
                        await session.scalars(
                            select(BookingOperation.id)
                            .where(
                                BookingOperation.state == "PENDING",
                                BookingOperation.created_at
                                < datetime.now(UTC) - timedelta(seconds=self.recovery_interval),
                            )
                            .order_by(BookingOperation.created_at)
                            .limit(100)
                        )
                    )
                for operation_id in operations:
                    try:
                        await self.recover_one(operation_id)
                    except Exception:
                        logger.exception("Recovery will retry operation=%s", operation_id)
            except Exception:
                logger.exception("Recovery scan failed")
