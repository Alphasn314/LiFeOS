#!/bin/sh
set -eu

python -m alembic -c /app/alembic.ini upgrade head
exec python -m uvicorn lifeos.main:app --host 0.0.0.0 --port 8000
