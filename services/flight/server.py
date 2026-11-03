import asyncio
import logging
import signal

import grpc

from generated import flight_pb2_grpc
from services.flight.cache import FlightCache
from services.flight.interceptors import ServerInterceptor
from services.flight.service import FlightService
from shared.config import Settings
from shared.database import database
from shared.logging import configure_logging


async def main():
    settings = Settings()
    configure_logging(settings.log_level)
    engine, sessions = database(settings.database_url)
    cache = FlightCache(settings)
    server = grpc.aio.server(
        interceptors=[ServerInterceptor(settings.grpc_api_key.get_secret_value())]
    )
    flight_pb2_grpc.add_FlightServiceServicer_to_server(FlightService(sessions, cache), server)
    server.add_insecure_port(f"[::]:{settings.grpc_port}")
    await server.start()
    logging.getLogger(__name__).info("Flight gRPC listening port=%s", settings.grpc_port)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await server.stop(5)
        await cache.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
