import asyncio
import base64
import json
import os
from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import uuid4

import grpc
import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from generated import flight_pb2 as pb
from services.booking.client import FlightClient
from services.booking.models import Booking, BookingOperation
from services.booking.schemas import CreateBooking
from services.booking.service import BookingService
from services.flight.cache import FlightCache
from services.flight.models import CacheRevision, Flight, SeatReservation
from shared.config import Settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Requires Compose"),
]


def booking_payload(flight, seats=2):
    return {
        "user_id": str(uuid4()),
        "flight_id": str(flight.id),
        "passenger_name": "Ivan Petrov",
        "passenger_email": "ivan@example.com",
        "seat_count": seats,
    }


async def test_rest_booking_snapshot_and_cancel(api, flight, grpc_call):
    search = await api.get(
        "/flights",
        params={
            "origin": "TST",
            "destination": "LED",
            "date": flight.departure_time.date().isoformat(),
        },
    )
    assert search.status_code == 200
    assert str(flight.id) in [item["id"] for item in search.json()]
    data = booking_payload(flight)
    created = await api.post("/bookings", json=data)
    assert created.status_code == 201, created.text
    booking = created.json()
    assert booking["status"] == "CONFIRMED"
    assert Decimal(booking["total_price"]) == Decimal("2469.12")
    assert (await api.get(f"/flights/{flight.id}")).json()["available_seats"] == 2
    await grpc_call(
        "UpdateFlight", pb.UpdateFlightRequest(flight_id=str(flight.id), price="2000.00")
    )
    assert (await api.get(f"/bookings/{booking['id']}")).json()["total_price"] == booking[
        "total_price"
    ]
    assert len((await api.get("/bookings", params={"user_id": data["user_id"]})).json()) == 1
    cancelled = await api.post(f"/bookings/{booking['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert (await api.get(f"/flights/{flight.id}")).json()["available_seats"] == 4
    assert (await api.post(f"/bookings/{booking['id']}/cancel")).status_code == 409


async def test_errors_do_not_create_booking(api, flight):
    data = booking_payload(flight, 5)
    response = await api.post("/bookings", json=data)
    assert response.status_code == 409
    assert response.json()["code"] == "RESOURCE_EXHAUSTED"
    assert (await api.get("/bookings", params={"user_id": data["user_id"]})).json() == []
    assert (await api.get(f"/flights/{flight.id}")).json()["available_seats"] == 4
    assert (await api.get(f"/flights/{uuid4()}")).status_code == 404
    assert (await api.get(f"/bookings/{uuid4()}")).status_code == 404
    assert (await api.post("/bookings", json={**data, "seat_count": 0})).status_code == 422
    assert (
        await api.get("/flights", params={"origin": "bad", "destination": "LED"})
    ).status_code == 422


@pytest.mark.parametrize("key", [None, "wrong-key"])
async def test_authentication_on_every_rpc(grpc_stub, key):
    metadata = [("x-api-key", key)] if key else []
    requests = {
        "GetFlight": pb.GetFlightRequest(),
        "SearchFlights": pb.SearchFlightsRequest(),
        "ReserveSeats": pb.ReserveSeatsRequest(),
        "ReleaseReservation": pb.ReleaseReservationRequest(),
        "UpdateFlight": pb.UpdateFlightRequest(),
    }
    for method, request in requests.items():
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await getattr(grpc_stub, method)(request, metadata=metadata, timeout=3)
        assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED


async def test_concurrent_last_seat(flight, grpc_call):
    await grpc_call("UpdateFlight", pb.UpdateFlightRequest(flight_id=str(flight.id), total_seats=1))
    requests = [
        pb.ReserveSeatsRequest(flight_id=str(flight.id), booking_id=str(uuid4()), seat_count=1)
        for _ in range(20)
    ]
    responses = await asyncio.gather(
        *(grpc_call("ReserveSeats", request) for request in requests), return_exceptions=True
    )
    successes = [response for response in responses if isinstance(response, pb.SeatReservation)]
    assert len(successes) == 1
    errors = [response for response in responses if isinstance(response, grpc.aio.AioRpcError)]
    assert len(errors) == 19
    assert all(error.code() == grpc.StatusCode.RESOURCE_EXHAUSTED for error in errors)
    result = await grpc_call("GetFlight", pb.GetFlightRequest(flight_id=str(flight.id)))
    assert result.available_seats == 0
    await grpc_call(
        "ReleaseReservation", pb.ReleaseReservationRequest(booking_id=successes[0].booking_id)
    )
    assert (
        await grpc_call("GetFlight", pb.GetFlightRequest(flight_id=str(flight.id)))
    ).available_seats == 1


async def test_idempotency_and_delayed_reserve_fencing(flight, grpc_call):
    booking_id = str(uuid4())
    request = pb.ReserveSeatsRequest(flight_id=str(flight.id), booking_id=booking_id, seat_count=2)
    reservations = await asyncio.gather(*(grpc_call("ReserveSeats", request) for _ in range(10)))
    assert len({reservation.id for reservation in reservations}) == 1
    assert (
        await grpc_call("GetFlight", pb.GetFlightRequest(flight_id=str(flight.id)))
    ).available_seats == 2
    with pytest.raises(grpc.aio.AioRpcError) as error:
        await grpc_call(
            "ReserveSeats",
            pb.ReserveSeatsRequest(flight_id=str(flight.id), booking_id=booking_id, seat_count=1),
        )
    assert error.value.code() == grpc.StatusCode.ALREADY_EXISTS
    await asyncio.gather(
        *(
            grpc_call("ReleaseReservation", pb.ReleaseReservationRequest(booking_id=booking_id))
            for _ in range(10)
        )
    )
    assert (
        await grpc_call("GetFlight", pb.GetFlightRequest(flight_id=str(flight.id)))
    ).available_seats == 4
    for fenced_id in [booking_id, str(uuid4())]:
        await grpc_call("ReleaseReservation", pb.ReleaseReservationRequest(booking_id=fenced_id))
        request.booking_id = fenced_id
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await grpc_call("ReserveSeats", request)
        assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION


async def test_cache_ttl_invalidation_and_stale_value_rejection(flight, grpc_call, flight_db):
    settings = Settings(database_url=os.environ["FLIGHT_DATABASE_URL"])
    cache = FlightCache(settings)
    try:
        request = pb.GetFlightRequest(flight_id=str(flight.id))
        day = Timestamp()
        day.FromDatetime(datetime.combine(flight.departure_time.date(), time.min, tzinfo=UTC))
        search = pb.SearchFlightsRequest(origin="TST", destination="LED", departure_date=day)
        old = await grpc_call("GetFlight", request)
        await grpc_call("SearchFlights", search)
        await grpc_call("SearchFlights", pb.SearchFlightsRequest(origin="TST", destination="LED"))
        keys = [
            f"flight:{flight.id}",
            f"search:TST:LED:{flight.departure_time.date()}",
            "search:TST:LED:all",
        ]
        for key in keys:
            assert 0 < await cache.redis.ttl(key) <= 600
        async with flight_db() as session:
            revision = await session.scalar(select(CacheRevision.revision))
        await grpc_call(
            "UpdateFlight", pb.UpdateFlightRequest(flight_id=str(flight.id), price="100.00")
        )
        assert all([not await cache.redis.exists(key) for key in keys])
        await cache.redis.set(
            keys[0],
            json.dumps(
                {
                    "revision": revision,
                    "payload": base64.b64encode(old.SerializeToString()).decode(),
                }
            ),
            ex=300,
        )
        assert (await grpc_call("GetFlight", request)).price == "100.00"
        await grpc_call(
            "UpdateFlight", pb.UpdateFlightRequest(flight_id=str(flight.id), status=pb.CANCELLED)
        )
        assert str(flight.id) not in [
            item.id for item in (await grpc_call("SearchFlights", search)).flights
        ]
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await grpc_call(
                "ReserveSeats",
                pb.ReserveSeatsRequest(
                    flight_id=str(flight.id), booking_id=str(uuid4()), seat_count=1
                ),
            )
        assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    finally:
        await cache.close()


async def test_database_constraints(flight, flight_db):
    for values in [{"available_seats": -1}, {"price": Decimal("0")}, {"total_seats": 0}]:
        with pytest.raises(IntegrityError):
            async with flight_db.begin() as session:
                row = await session.get(Flight, flight.id)
                for key, value in values.items():
                    setattr(row, key, value)
    with pytest.raises(IntegrityError):
        async with flight_db.begin() as session:
            row = Flight(
                **{
                    column.name: getattr(flight, column.name)
                    for column in Flight.__table__.columns
                    if column.name != "id"
                }
            )
            session.add(row)


async def test_recovery_after_crash_between_reservation_and_booking(flight, booking_db, grpc_call):
    client = FlightClient(Settings(database_url=os.environ["BOOKING_DATABASE_URL"]))
    service = BookingService(booking_db, client)
    booking_id = uuid4()
    try:
        operation_id = await service.operation(booking_id, "CREATE")
        await grpc_call(
            "ReserveSeats",
            pb.ReserveSeatsRequest(
                flight_id=str(flight.id), booking_id=str(booking_id), seat_count=2
            ),
        )
        await service.recover_one(operation_id)
        await service.recover_one(operation_id)
        async with booking_db() as session:
            assert await session.get(Booking, booking_id) is None
            assert (await session.get(BookingOperation, operation_id)).state == "DONE"
        assert (
            await grpc_call("GetFlight", pb.GetFlightRequest(flight_id=str(flight.id)))
        ).available_seats == 4
    finally:
        await client.close()


async def test_compensation_after_booking_write_failure(flight, booking_db, flight_db, grpc_call):
    client = FlightClient(Settings(database_url=os.environ["BOOKING_DATABASE_URL"]))
    service = BookingService(booking_db, client)
    payload = booking_payload(flight)
    payload["passenger_name"] = "x" * 201
    data = CreateBooking.model_construct(**{**payload, "flight_id": flight.id})
    try:
        with pytest.raises(SQLAlchemyError):
            await service.create(data)
        async with flight_db() as session:
            reservations = list(
                await session.scalars(
                    select(SeatReservation).where(SeatReservation.flight_id == flight.id)
                )
            )
            assert len(reservations) == 1
            assert reservations[0].status == "RELEASED"
        assert (
            await grpc_call("GetFlight", pb.GetFlightRequest(flight_id=str(flight.id)))
        ).available_seats == 4
    finally:
        await client.close()


async def test_cancel_recovery_after_remote_release(api, flight, booking_db, grpc_call):
    created = await api.post("/bookings", json=booking_payload(flight))
    assert created.status_code == 201
    from uuid import UUID

    booking_id = UUID(created.json()["id"])
    client = FlightClient(Settings(database_url=os.environ["BOOKING_DATABASE_URL"]))
    service = BookingService(booking_db, client)
    try:
        operation_id = await service.operation(booking_id, "CANCEL")
        await grpc_call(
            "ReleaseReservation", pb.ReleaseReservationRequest(booking_id=str(booking_id))
        )
        await service.recover_one(operation_id)
        assert (await api.get(f"/bookings/{booking_id}")).json()["status"] == "CANCELLED"
        assert (
            await grpc_call("GetFlight", pb.GetFlightRequest(flight_id=str(flight.id)))
        ).available_seats == 4
    finally:
        await client.close()
