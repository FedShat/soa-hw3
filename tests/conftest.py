import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import grpc
import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from generated import flight_pb2_grpc as rpc
from services.booking.models import Booking, BookingOperation
from services.flight.models import Airline, Flight, ReservationCancellation, SeatReservation
from services.flight.service import bump_revision
from shared.database import database


@pytest.fixture
async def api():
    async with httpx.AsyncClient(base_url=os.environ["API_URL"], timeout=15) as client:
        yield client


@pytest.fixture
async def flight_db():
    engine, sessions = database(os.environ["FLIGHT_DATABASE_URL"])
    yield sessions
    await engine.dispose()


@pytest.fixture
async def booking_db():
    engine, sessions = database(os.environ["BOOKING_DATABASE_URL"])
    yield sessions
    await engine.dispose()


@pytest.fixture
async def flight(flight_db, booking_db):
    departure = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)
    async with flight_db.begin() as session:
        await session.execute(
            insert(Airline).values(code="ZZ", name="Test Air").on_conflict_do_nothing()
        )
        row = Flight(
            id=uuid4(),
            flight_number=f"ZZ{uuid4().hex[:10]}",
            airline_code="ZZ",
            origin="TST",
            destination="LED",
            departure_time=departure,
            arrival_time=departure + timedelta(hours=2),
            total_seats=4,
            available_seats=4,
            price=Decimal("1234.56"),
            currency="RUB",
            status="SCHEDULED",
        )
        session.add(row)
        await bump_revision(session)
    yield row
    async with booking_db.begin() as session:
        ids = list(await session.scalars(select(Booking.id).where(Booking.flight_id == row.id)))
        await session.execute(delete(BookingOperation).where(BookingOperation.booking_id.in_(ids)))
        await session.execute(delete(Booking).where(Booking.flight_id == row.id))
    async with flight_db.begin() as session:
        ids = list(
            await session.scalars(
                select(SeatReservation.booking_id).where(SeatReservation.flight_id == row.id)
            )
        )
        await session.execute(delete(SeatReservation).where(SeatReservation.flight_id == row.id))
        await session.execute(
            delete(ReservationCancellation).where(ReservationCancellation.booking_id.in_(ids))
        )
        await session.execute(delete(Flight).where(Flight.id == row.id))
        await bump_revision(session)


@pytest.fixture
async def grpc_stub():
    async with grpc.aio.insecure_channel(os.environ["GRPC_TARGET"]) as channel:
        yield rpc.FlightServiceStub(channel)


@pytest.fixture
def grpc_call(grpc_stub):
    async def call(method, request):
        return await getattr(grpc_stub, method)(
            request, metadata=[("x-api-key", os.environ["GRPC_API_KEY"])], timeout=5
        )

    return call
