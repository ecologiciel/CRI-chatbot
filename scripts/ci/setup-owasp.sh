#!/usr/bin/env bash
# Seed OWASP API tests only in a fresh, explicitly isolated CI database.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" || "${POSTGRES_HOST:-}" != "localhost" ]]; then
  echo "Refusing OWASP fixture setup outside GitHub's isolated service database" >&2
  exit 1
fi

python - <<'PY'
import asyncio
import os
import asyncpg

async def main():
    connection = await asyncpg.connect(
        host=os.environ["POSTGRES_HOST"], port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"], database="postgres",
    )
    try:
        await connection.execute("CREATE DATABASE owasp_ci")
    finally:
        await connection.close()

asyncio.run(main())
PY
export POSTGRES_DB=owasp_ci OWASP_ASGI_ISOLATED=1
cd backend
alembic upgrade head
python -m tests.security.owasp.seed_ci
