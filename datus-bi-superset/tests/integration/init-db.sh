#!/bin/bash
# Create Superset metadata DB and deterministic BI fixture tables.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE superset_meta OWNER $POSTGRES_USER'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'superset_meta')\gexec

    CREATE TABLE IF NOT EXISTS public.datus_nightly_bi_sales (
        sale_id integer PRIMARY KEY,
        region text NOT NULL,
        channel text NOT NULL,
        revenue numeric(12, 2) NOT NULL,
        orders integer NOT NULL,
        sale_date date NOT NULL
    );

    TRUNCATE TABLE public.datus_nightly_bi_sales;

    INSERT INTO public.datus_nightly_bi_sales
        (sale_id, region, channel, revenue, orders, sale_date)
    VALUES
        (1, 'North', 'Online', 1200.00, 12, DATE '2026-01-01'),
        (2, 'North', 'Partner', 850.00, 7, DATE '2026-01-02'),
        (3, 'South', 'Online', 990.00, 9, DATE '2026-01-03'),
        (4, 'South', 'Retail', 640.00, 5, DATE '2026-01-04'),
        (5, 'West', 'Online', 1510.00, 14, DATE '2026-01-05'),
        (6, 'West', 'Partner', 430.00, 4, DATE '2026-01-06');
EOSQL
