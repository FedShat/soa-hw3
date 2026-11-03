.PHONY: up down logs test unit lint proto install resilience

up:
	docker compose up --build -d --wait

down:
	docker compose down

logs:
	docker compose logs -f booking flight

test:
	docker compose up --build -d --wait
	docker compose --profile test run --build --rm tests

unit: proto
	uv run python -m pytest -q -m "not integration"

lint:
	uv run ruff check .
	uv run ruff format --check .

proto:
	uv run python -m scripts.generate_proto

install:
	uv sync --frozen
	uv run python -m scripts.generate_proto

resilience:
	python3 -m scripts.check_resilience
