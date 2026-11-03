import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import date as Date
from uuid import UUID

import grpc
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from services.booking.client import FlightClient
from services.booking.resilience import CircuitOpenError
from services.booking.schemas import BookingResponse, CreateBooking, FlightResponse
from services.booking.service import BookingService
from shared.config import Settings
from shared.database import database
from shared.logging import configure_logging


@asynccontextmanager
async def lifespan(app):
    settings = Settings()
    configure_logging(settings.log_level)
    engine, sessions = database(settings.database_url)
    flights = FlightClient(settings)
    service = BookingService(sessions, flights, settings.recovery_interval)
    app.state.engine = engine
    app.state.flights = flights
    app.state.bookings = service
    recovery = asyncio.create_task(service.recovery_loop())
    try:
        yield
    finally:
        recovery.cancel()
        with suppress(asyncio.CancelledError):
            await recovery
        await flights.close()
        await engine.dispose()


app = FastAPI(title="Flight Booking API", version="1.0.0", lifespan=lifespan)


@app.exception_handler(grpc.aio.AioRpcError)
async def grpc_error(request, error):
    statuses = {
        grpc.StatusCode.INVALID_ARGUMENT: 422,
        grpc.StatusCode.NOT_FOUND: 404,
        grpc.StatusCode.RESOURCE_EXHAUSTED: 409,
        grpc.StatusCode.ALREADY_EXISTS: 409,
        grpc.StatusCode.FAILED_PRECONDITION: 409,
        grpc.StatusCode.UNAUTHENTICATED: 502,
        grpc.StatusCode.PERMISSION_DENIED: 502,
        grpc.StatusCode.UNAVAILABLE: 503,
        grpc.StatusCode.DEADLINE_EXCEEDED: 504,
    }
    return JSONResponse(
        status_code=statuses.get(error.code(), 502),
        content={"detail": error.details(), "code": error.code().name},
    )


@app.exception_handler(CircuitOpenError)
async def circuit_error(request, error):
    return JSONResponse(status_code=503, content={"detail": str(error), "code": "CIRCUIT_OPEN"})


@app.exception_handler(SQLAlchemyError)
async def database_error(request, error):
    return JSONResponse(status_code=503, content={"detail": "Booking database is unavailable"})


@app.get("/health", tags=["system"])
async def health(request: Request):
    async with request.app.state.engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok", "flight_circuit": request.app.state.flights.interceptor.breaker.state}


@app.get("/flights", response_model=list[FlightResponse], tags=["flights"])
async def search_flights(
    request: Request,
    origin: str = Query(pattern="^[A-Z]{3}$"),
    destination: str = Query(pattern="^[A-Z]{3}$"),
    date: Date | None = None,
):
    if origin == destination:
        raise HTTPException(422, "Origin and destination must differ")
    result = await request.app.state.flights.search(origin, destination, date)
    return [FlightResponse.from_proto(flight) for flight in result.flights]


@app.get("/flights/{flight_id}", response_model=FlightResponse, tags=["flights"])
async def get_flight(flight_id: UUID, request: Request):
    return FlightResponse.from_proto(await request.app.state.flights.get(flight_id))


@app.post("/bookings", response_model=BookingResponse, status_code=201, tags=["bookings"])
async def create_booking(data: CreateBooking, request: Request):
    return await request.app.state.bookings.create(data)


@app.get("/bookings", response_model=list[BookingResponse], tags=["bookings"])
async def list_bookings(request: Request, user_id: str = Query(min_length=1, max_length=128)):
    return await request.app.state.bookings.list(user_id)


@app.get("/bookings/{booking_id}", response_model=BookingResponse, tags=["bookings"])
async def get_booking(booking_id: UUID, request: Request):
    return await request.app.state.bookings.get(booking_id)


@app.post("/bookings/{booking_id}/cancel", response_model=BookingResponse, tags=["bookings"])
async def cancel_booking(booking_id: UUID, request: Request):
    return await request.app.state.bookings.cancel(booking_id)
