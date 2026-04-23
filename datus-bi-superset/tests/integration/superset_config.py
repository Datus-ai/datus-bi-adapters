"""
Superset configuration: route both metadata and examples storage to
PostgreSQL so host-side tools (``write_query``) can share the DB the
Superset UI reads from.

Without ``SQLALCHEMY_EXAMPLES_URI`` Superset falls back to its default
in-image SQLite for the examples database, leaving host-produced tables
invisible to ``database_id=1`` and breaking the
``write_query -> create_dataset`` handshake.
"""

SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://superset:superset@postgres:5432/superset_meta"
)

SQLALCHEMY_EXAMPLES_URI = (
    "postgresql+psycopg2://superset:superset@postgres:5432/superset_examples"
)
