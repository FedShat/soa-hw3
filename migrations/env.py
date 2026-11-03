import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from services.booking.models import Base as BookingBase
from services.flight.models import Base as FlightBase

metadata = FlightBase.metadata if os.environ["SERVICE"] == "flight" else BookingBase.metadata


def run(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        await connection.run_sync(run)
    await engine.dispose()


asyncio.run(main())
