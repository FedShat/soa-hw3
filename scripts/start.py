import asyncio
import os

from scripts.migrate import main as migrate


def main():
    migrate()
    if os.environ["SERVICE"] == "flight":
        from services.flight.seed import seed

        asyncio.run(seed())
        os.execvp("python", ["python", "-m", "services.flight.server"])
    os.execvp(
        "uvicorn",
        ["uvicorn", "services.booking.app:app", "--host", "0.0.0.0", "--port", "8000"],
    )


if __name__ == "__main__":
    main()
