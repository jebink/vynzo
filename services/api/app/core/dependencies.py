"""FastAPI dependencies shared across modules."""

from collections.abc import Iterator

import psycopg
from fastapi import Request


def get_db(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.db_pool.connection() as conn:
        yield conn
