from datetime import UTC, datetime, time

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from generated import flight_pb2 as pb
from generated import flight_pb2_grpc as rpc
from services.booking.resilience import ResilienceInterceptor


class FlightClient:
    def __init__(self, settings):
        self.interceptor = ResilienceInterceptor(settings)
        self.channel = grpc.aio.insecure_channel(
            settings.grpc_target,
            interceptors=[self.interceptor],
            options=[("grpc.enable_retries", 0)],
        )
        self.stub = rpc.FlightServiceStub(self.channel)

    async def search(self, origin, destination, date):
        request = pb.SearchFlightsRequest(origin=origin, destination=destination)
        if date is not None:
            timestamp = Timestamp()
            timestamp.FromDatetime(datetime.combine(date, time.min, tzinfo=UTC))
            request.departure_date.CopyFrom(timestamp)
        return await self.stub.SearchFlights(request)

    async def get(self, flight_id):
        return await self.stub.GetFlight(pb.GetFlightRequest(flight_id=str(flight_id)))

    async def reserve(self, flight_id, seat_count, booking_id):
        return await self.stub.ReserveSeats(
            pb.ReserveSeatsRequest(
                flight_id=str(flight_id), seat_count=seat_count, booking_id=str(booking_id)
            )
        )

    async def release(self, booking_id):
        return await self.stub.ReleaseReservation(
            pb.ReleaseReservationRequest(booking_id=str(booking_id))
        )

    async def close(self):
        await self.channel.close()
