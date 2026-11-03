from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from generated import flight_pb2 as pb


class CreateBooking(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=128)
    flight_id: UUID
    passenger_name: str = Field(min_length=1, max_length=200)
    passenger_email: EmailStr = Field(max_length=254)
    seat_count: int = Field(ge=1, le=1_000_000, strict=True)


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: str
    flight_id: UUID
    passenger_name: str
    passenger_email: str
    seat_count: int
    total_price: Decimal
    currency: str
    status: Literal["CONFIRMED", "CANCELLED"]
    created_at: datetime


class FlightResponse(BaseModel):
    id: UUID
    flight_number: str
    airline_code: str
    airline_name: str
    origin: str
    destination: str
    departure_time: datetime
    arrival_time: datetime
    total_seats: int
    available_seats: int
    price: Decimal
    currency: str
    status: Literal["SCHEDULED", "DEPARTED", "CANCELLED", "COMPLETED"]

    @classmethod
    def from_proto(cls, flight):
        return cls(
            **{
                field: getattr(flight, field)
                for field in cls.model_fields
                if field not in {"status", "departure_time", "arrival_time"}
            },
            status=pb.FlightStatus.Name(flight.status),
            departure_time=flight.departure_time.ToDatetime(tzinfo=UTC),
            arrival_time=flight.arrival_time.ToDatetime(tzinfo=UTC),
        )
