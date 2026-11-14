"""Database connection helper."""

import psycopg
from psycopg.rows import dict_row


def connect(url: str) -> psycopg.Connection:
    """Open a connection with dict rows and autocommit off.

    The caller owns the transaction: every store function in this package leaves commit and
    rollback to whoever holds the connection.
    """
    return psycopg.connect(url, row_factory=dict_row, autocommit=False)
