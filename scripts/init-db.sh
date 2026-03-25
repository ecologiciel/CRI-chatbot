#!/bin/bash
set -e

# =============================================================================
# CRI Platform — PostgreSQL initialization script
# Executed once at first container startup via /docker-entrypoint-initdb.d/
# =============================================================================

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Extensions requises
    CREATE EXTENSION IF NOT EXISTS pgcrypto;
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

    -- Les schemas tenant_xxx seront crees dynamiquement
    -- par le service de provisionnement (Alembic + API)
EOSQL

echo "PostgreSQL initialized with pgcrypto and uuid-ossp extensions"
