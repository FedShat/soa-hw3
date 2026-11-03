from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from services.flight.models import Airline, Flight
from shared.config import Settings
from shared.database import database


async def seed():
    settings = Settings()
    if not settings.seed_demo:
        return
    engine, sessions = database(settings.database_url)
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    async with sessions.begin() as session:
        await session.execute(
            insert(Airline)
            .values([{"code": "SU", "name": "Aeroflot"}, {"code": "DP", "name": "Pobeda"}])
            .on_conflict_do_nothing()
        )
        for index, (origin, destination, seats, price) in enumerate(
            [
                ("SVO", "LED", 180, "6500.00"),
                ("SVO", "LED", 30, "7200.50"),
                ("VKO", "AER", 120, "12500.00"),
                ("LED", "SVO", 180, "6100.00"),
            ],
            start=1,
        ):
            departure = tomorrow + timedelta(hours=index * 2)
            await session.execute(
                insert(Flight)
                .values(
                    id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
                    flight_number=f"{'DP' if index == 3 else 'SU'}{1000 + index}",
                    airline_code="DP" if index == 3 else "SU",
                    origin=origin,
                    destination=destination,
                    departure_time=departure,
                    arrival_time=departure + timedelta(hours=2),
                    total_seats=seats,
                    available_seats=seats,
                    price=Decimal(price),
                    currency="RUB",
                    status="SCHEDULED",
                )
                .on_conflict_do_nothing()
            )
    await engine.dispose()
