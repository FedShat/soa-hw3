import asyncio
import os
import urllib.request

import grpc

from generated import flight_pb2, flight_pb2_grpc


async def check_grpc():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = flight_pb2_grpc.FlightServiceStub(channel)
        await stub.GetFlight(
            flight_pb2.GetFlightRequest(flight_id="00000000-0000-0000-0000-000000000000"),
            metadata=[("x-api-key", os.environ["GRPC_API_KEY"])],
            timeout=2,
        )


def main():
    if os.environ["SERVICE"] == "booking":
        with urllib.request.urlopen("http://localhost:8000/health", timeout=2) as response:
            if response.status != 200:
                raise SystemExit(1)
    else:
        try:
            asyncio.run(check_grpc())
        except grpc.aio.AioRpcError as error:
            if error.code() != grpc.StatusCode.NOT_FOUND:
                raise


if __name__ == "__main__":
    main()
