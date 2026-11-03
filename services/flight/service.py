import re
from datetime import UTC, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from sqlalchemy import select, text, update

from generated import flight_pb2 as pb
from generated import flight_pb2_grpc as rpc
from services.flight.interceptors import BusinessError
from services.flight.models import (
    CacheRevision,
    Flight,
    ReservationCancellation,
    SeatReservation,
)


def timestamp(value):
    result = Timestamp()
    result.FromDatetime(value)
    return result


def flight_message(flight):
    return pb.Flight(
        id=str(flight.id),
        flight_number=flight.flight_number,
        airline_code=flight.airline_code,
        airline_name=flight.airline.name,
        origin=flight.origin,
        destination=flight.destination,
        departure_time=timestamp(flight.departure_time),
        arrival_time=timestamp(flight.arrival_time),
        total_seats=flight.total_seats,
        available_seats=flight.available_seats,
        price=str(flight.price),
        currency=flight.currency,
        status=pb.FlightStatus.Value(flight.status),
    )


def reservation_message(reservation):
    return pb.SeatReservation(
        id=str(reservation.id),
        flight_id=str(reservation.flight_id),
        booking_id=str(reservation.booking_id),
        seat_count=reservation.seat_count,
        status=pb.ReservationStatus.Value(reservation.status),
        created_at=timestamp(reservation.created_at),
    )


async def lock_booking(session, booking_id):
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": booking_id.int % (2**63)},
    )


async def bump_revision(session):
    await session.execute(update(CacheRevision).values(revision=CacheRevision.revision + 1))


async def get_locked_flight(session, flight_id):
    flight = await session.scalar(
        select(Flight).where(Flight.id == flight_id).with_for_update(of=Flight)
    )
    if flight is None:
        raise BusinessError(grpc.StatusCode.NOT_FOUND, "Flight not found")
    return flight


class FlightService(rpc.FlightServiceServicer):
    def __init__(self, sessions, cache):
        self.sessions = sessions
        self.cache = cache

    async def SearchFlights(self, request, context):
        if not all(
            re.fullmatch(r"[A-Z]{3}", code) for code in (request.origin, request.destination)
        ):
            raise ValueError("Airports must be uppercase IATA codes")
        if request.origin == request.destination:
            raise ValueError("Origin and destination must differ")
        start = None
        if request.HasField("departure_date"):
            start = request.departure_date.ToDatetime(tzinfo=UTC)
            if start.hour or start.minute or start.second or request.departure_date.nanos:
                raise ValueError("departure_date must be midnight UTC")
        day = start.date().isoformat() if start else "all"
        key = f"search:{request.origin}:{request.destination}:{day}"
        async with self.sessions() as session:
            revision = await session.scalar(select(CacheRevision.revision))
            cached = await self.cache.get(key, revision, pb.SearchFlightsResponse)
            if cached is not None:
                return cached
            query = select(Flight).where(
                Flight.origin == request.origin,
                Flight.destination == request.destination,
                Flight.status == "SCHEDULED",
            )
            if start:
                query = query.where(
                    Flight.departure_time >= start,
                    Flight.departure_time < start + timedelta(days=1),
                )
            flights = await session.scalars(query.order_by(Flight.departure_time, Flight.id))
            response = pb.SearchFlightsResponse(flights=[flight_message(f) for f in flights])
        await self.cache.set(key, revision, response)
        return response

    async def GetFlight(self, request, context):
        flight_id = UUID(request.flight_id)
        key = f"flight:{flight_id}"
        async with self.sessions() as session:
            revision = await session.scalar(select(CacheRevision.revision))
            cached = await self.cache.get(key, revision, pb.Flight)
            if cached is not None:
                return cached
            flight = await session.get(Flight, flight_id)
            if flight is None:
                raise BusinessError(grpc.StatusCode.NOT_FOUND, "Flight not found")
            response = flight_message(flight)
        await self.cache.set(key, revision, response)
        return response

    async def ReserveSeats(self, request, context):
        flight_id, booking_id = UUID(request.flight_id), UUID(request.booking_id)
        if not 1 <= request.seat_count <= 1_000_000:
            raise ValueError("seat_count must be between 1 and 1000000")
        async with self.sessions.begin() as session:
            await lock_booking(session, booking_id)
            cancelled = await session.get(ReservationCancellation, booking_id)
            if cancelled:
                raise BusinessError(grpc.StatusCode.FAILED_PRECONDITION, "Reservation was released")
            reservation = await session.scalar(
                select(SeatReservation).where(SeatReservation.booking_id == booking_id)
            )
            if reservation:
                if (
                    reservation.flight_id != flight_id
                    or reservation.seat_count != request.seat_count
                ):
                    raise BusinessError(
                        grpc.StatusCode.ALREADY_EXISTS,
                        "booking_id already has different parameters",
                    )
                if reservation.status != "ACTIVE":
                    raise BusinessError(
                        grpc.StatusCode.FAILED_PRECONDITION, "Reservation is inactive"
                    )
                return reservation_message(reservation)
            flight = await get_locked_flight(session, flight_id)
            if flight.status != "SCHEDULED":
                raise BusinessError(grpc.StatusCode.FAILED_PRECONDITION, "Flight is not scheduled")
            if flight.available_seats < request.seat_count:
                raise BusinessError(
                    grpc.StatusCode.RESOURCE_EXHAUSTED, "Not enough available seats"
                )
            flight.available_seats -= request.seat_count
            reservation = SeatReservation(
                flight_id=flight_id, booking_id=booking_id, seat_count=request.seat_count
            )
            session.add(reservation)
            await bump_revision(session)
            await session.flush()
            response = reservation_message(reservation)
        await self.cache.invalidate(flight)
        return response

    async def ReleaseReservation(self, request, context):
        booking_id = UUID(request.booking_id)
        flight = None
        async with self.sessions.begin() as session:
            await lock_booking(session, booking_id)
            if not await session.get(ReservationCancellation, booking_id):
                session.add(ReservationCancellation(booking_id=booking_id))
            reservation = await session.scalar(
                select(SeatReservation)
                .where(SeatReservation.booking_id == booking_id)
                .with_for_update()
            )
            if reservation and reservation.status == "ACTIVE":
                flight = await get_locked_flight(session, reservation.flight_id)
                flight.available_seats += reservation.seat_count
                reservation.status = "RELEASED"
                await bump_revision(session)
        if flight is not None:
            await self.cache.invalidate(flight)
        return pb.ReleaseReservationResponse(booking_id=str(booking_id), status=pb.RELEASED)

    async def UpdateFlight(self, request, context):
        flight_id = UUID(request.flight_id)
        if not any(request.HasField(field) for field in ("price", "total_seats", "status")):
            raise ValueError("At least one field must be provided")
        price = None
        if request.HasField("price"):
            try:
                price = Decimal(request.price)
                if (
                    not price.is_finite()
                    or not 0 < price <= Decimal("9999999999.99")
                    or price != price.quantize(Decimal("0.01"))
                ):
                    raise ValueError("Price must be positive with at most two decimal places")
            except InvalidOperation as error:
                raise ValueError("Invalid price") from error
        if request.HasField("status") and request.status not in {
            pb.SCHEDULED,
            pb.DEPARTED,
            pb.CANCELLED,
            pb.COMPLETED,
        }:
            raise ValueError("Invalid flight status")
        if request.HasField("total_seats") and not 1 <= request.total_seats <= 1_000_000:
            raise ValueError("total_seats must be between 1 and 1000000")
        async with self.sessions.begin() as session:
            flight = await get_locked_flight(session, flight_id)
            if price is not None:
                flight.price = price
            if request.HasField("status"):
                flight.status = pb.FlightStatus.Name(request.status)
            if request.HasField("total_seats"):
                reserved = flight.total_seats - flight.available_seats
                if request.total_seats < reserved:
                    raise BusinessError(
                        grpc.StatusCode.FAILED_PRECONDITION, "Capacity is below reserved seat count"
                    )
                flight.total_seats = request.total_seats
                flight.available_seats = request.total_seats - reserved
            await bump_revision(session)
            await session.flush()
            response = flight_message(flight)
        await self.cache.invalidate(flight)
        return response
