#!/bin/bash
# Create grafana_meta database for Grafana internal metadata storage
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE grafana_meta OWNER grafana'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'grafana_meta')\gexec
EOSQL
