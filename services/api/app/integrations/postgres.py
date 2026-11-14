"""PostgreSQL / TimescaleDB connection pool. The schema is owned by database/postgres/migrations."""

from psycopg_pool import ConnectionPool


def create_pool(database_url: str) -> ConnectionPool:
    # open=False: the API must start even when the database is unreachable.
    # /health/ready reports database status.
    return ConnectionPool(database_url, min_size=1, max_size=10, open=False)
