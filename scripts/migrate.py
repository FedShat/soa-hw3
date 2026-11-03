import os

from alembic import command
from alembic.config import Config


def main() -> None:
    service = os.environ["SERVICE"]
    if service not in {"booking", "flight"}:
        raise ValueError("SERVICE must be booking or flight")
    config = Config("alembic.ini")
    config.set_main_option("version_locations", f"migrations/{service}")
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
