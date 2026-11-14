"""Business use cases for instruments. Calls the repository; knows nothing about HTTP."""

from typing import Any

import psycopg

from app.modules.instruments import repository


class ListingNotFound(Exception):
    """Raised when an exchange/symbol pair has no listing."""


def search(
    conn: psycopg.Connection, *, q: str | None, exchange: str | None, active: bool, limit: int
) -> list[dict[str, Any]]:
    return repository.search_listings(conn, q=q, exchange=exchange, active=active, limit=limit)


def require_listing(conn: psycopg.Connection, exchange: str, symbol: str) -> dict[str, Any]:
    listing = repository.get_listing(conn, exchange, symbol)
    if listing is None:
        raise ListingNotFound
    return listing


def listing_detail(conn: psycopg.Connection, exchange: str, symbol: str) -> dict[str, Any]:
    listing = require_listing(conn, exchange, symbol)
    bars = repository.latest_two_bars(conn, listing["listing_id"])
    return {
        **listing,
        "latest": bars[0] if bars else None,
        "previous_close": bars[1]["close"] if len(bars) > 1 else None,
    }


# ---- Ingestion selection ----
# Selecting a (exchange, symbol) sets listings.is_active, which the daily EOD ingestion,
# indicators and signals all run over. A newly selected listing has no checkpoint, so the next
# daily run fetches its full history.

PROVIDER = "yahoo"
# Yahoo Finance ticker suffix per exchange, e.g. RELIANCE.NS / RELIANCE.BO.
PROVIDER_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


class SymbolNotFound(Exception):
    """No listing with this symbol exists on any exchange."""


class CannotListOnExchange(Exception):
    """The symbol has no company (an index or an unlinked listing) to create a listing for."""


def _listing_state(row: dict[str, Any], prefix: str, last_bars: dict[int, Any]):
    listing_id = row[f"{prefix}_listing_id"]
    if listing_id is None:
        return None
    return {
        "listing_id": listing_id,
        "is_active": row[f"{prefix}_is_active"],
        "provider_symbol": row[f"{prefix}_provider_symbol"],
        "last_bar": last_bars.get(listing_id),
    }


def _shape_rows(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Only listings with a provider symbol can have been ingested, so only those are looked up.
    ingested = [
        row[f"{p}_listing_id"]
        for row in rows
        for p in ("nse", "bse")
        if row[f"{p}_provider_symbol"] is not None
    ]
    last_bars = repository.last_bar_times(conn, ingested)
    return [
        {
            "symbol": row["symbol"],
            "company_name": row["company_name"],
            "isin": row["isin"],
            "kind": row["kind"],
            "nse": _listing_state(row, "nse", last_bars),
            "bse": _listing_state(row, "bse", last_bars),
        }
        for row in rows
    ]


def list_selection(
    conn: psycopg.Connection, *, q: str | None, status: str, offset: int, limit: int
) -> dict[str, Any]:
    total, rows = repository.search_selection(
        conn, q=q, status=status, offset=offset, limit=limit, provider=PROVIDER
    )
    counts = repository.selected_counts(conn)
    return {
        "total": total,
        "selected": {exchange: counts.get(exchange, 0) for exchange in PROVIDER_SUFFIX},
        "rows": _shape_rows(conn, rows),
    }


def set_selection(
    conn: psycopg.Connection, exchange: str, symbol: str, *, selected: bool
) -> dict[str, Any]:
    """Select or deselect one (exchange, symbol) for the daily pipeline; returns its row.

    Selecting adds the Yahoo provider symbol when missing. Selecting BSE for a symbol that is
    only listed on NSE creates the BSE listing for the same company. Deselecting a listing that
    does not exist is a no-op.
    """
    exchange = exchange.upper()
    with conn.transaction():
        listings = repository.symbol_listings(conn, symbol)
        if not listings:
            raise SymbolNotFound
        target = next((x for x in listings if x["exchange"] == exchange), None)
        if target is None and selected:
            base = next((x for x in listings if x["company_id"] is not None), None)
            if base is None or base["kind"] != "equity":
                raise CannotListOnExchange
            listing_id = repository.create_listing(
                conn, exchange=exchange, symbol=symbol, kind="equity", company_id=base["company_id"]
            )
            target = {"listing_id": listing_id}
        if target is not None:
            repository.set_active(conn, target["listing_id"], selected)
            if selected:
                repository.ensure_provider_symbol(
                    conn,
                    provider=PROVIDER,
                    provider_symbol=f"{symbol}{PROVIDER_SUFFIX[exchange]}",
                    listing_id=target["listing_id"],
                )
    row = repository.selection_row(conn, symbol, PROVIDER)
    return _shape_rows(conn, [row])[0]
