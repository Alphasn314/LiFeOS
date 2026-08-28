FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/lifeos /app/lifeos
RUN python -m pip install --no-cache-dir .

COPY backend/alembic.ini /app/alembic.ini
COPY backend/migrations /app/migrations
COPY backend/docker-entrypoint.sh /app/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
