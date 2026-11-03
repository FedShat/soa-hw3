FROM python:3.13-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock .
RUN pip install -r requirements.lock
COPY . .
RUN python -m scripts.generate_proto && useradd --create-home app
USER app
CMD ["python", "-m", "scripts.start"]

FROM app AS test
USER root
RUN pip install -r requirements-dev.lock
USER app
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
