"""Reference-data sync: companies and listings from the NSE/BSE reference CSVs.

`sync_reference` takes an open connection and does NOT commit; the caller owns the transaction,
so the whole sync is one unit that commits or rolls back together.
"""

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import psycopg


@dataclass(frozen=True)
class SyncReport:
    companies_upserted: int
    listings_created: int
    listings_linked: int
    unlinked_bse: list[str] = field(default_factory=list)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(f)
        ]


def _date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%d-%b-%Y").date()
    except ValueError:
        return None


def sync_reference(conn: psycopg.Connection, nse_csv: Path, bse_csv: Path) -> SyncReport:
    """Idempotently load NSE companies and listings and link existing BSE listings.

    - Companies are upserted on ISIN (name updated). `companies_upserted` counts rows inserted
      or whose name changed.
    - NSE listings are matched on (exchange, symbol): existing equity listings get company_id,
      series and listed_on filled; new ones are created inactive with no provider symbol.
      `is_active` is never changed and index listings are never created or touched.
    - Existing BSE equity listings whose symbol is in `bse_csv` are linked to the company of the
      NSE listing with the same symbol. `unlinked_bse` lists "BSE:SYM" for BSE equity listings
      still without a company afterwards.
    - `listings_linked` counts existing listings whose company_id was set or changed.
    Does not commit.
    """
    nse: dict[str, dict] = {}
    for r in _read(nse_csv):
        sym = r.get("SYMBOL", "")
        if sym:
            nse[sym] = {
                "symbol": sym,
                "name": r.get("NAME OF COMPANY", ""),
                "series": r.get("SERIES") or None,
                "listed_on": _date(r.get("DATE OF LISTING", "")),
                "isin": r.get("ISIN NUMBER") or None,
            }
    bse_symbols = sorted({r["symbol"] for r in _read(bse_csv) if r.get("symbol")})

    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _ref_nse")
        cur.execute(
            "CREATE TEMP TABLE _ref_nse (symbol text PRIMARY KEY, name text, series text, "
            "listed_on date, isin text) ON COMMIT DROP"
        )
        cur.executemany(
            "INSERT INTO _ref_nse VALUES "
            "(%(symbol)s, %(name)s, %(series)s, %(listed_on)s, %(isin)s)",
            list(nse.values()),
        )

        cur.execute(
            "INSERT INTO companies (name, isin) "
            "SELECT DISTINCT ON (isin) name, isin FROM _ref_nse "
            "WHERE isin IS NOT NULL AND name <> '' ORDER BY isin, symbol "
            "ON CONFLICT (isin) DO UPDATE SET name = EXCLUDED.name "
            "WHERE companies.name IS DISTINCT FROM EXCLUDED.name"
        )
        companies = cur.rowcount

        cur.execute(
            "WITH t AS ("
            "  SELECT l.listing_id, c.company_id AS new_cid, "
            "         l.company_id IS DISTINCT FROM c.company_id AS relinked, "
            "         s.series, s.listed_on "
            "  FROM listings l JOIN _ref_nse s ON l.symbol = s.symbol "
            "  JOIN companies c ON c.isin = s.isin "
            "  WHERE l.exchange = 'NSE' AND l.kind = 'equity' AND ("
            "    l.company_id IS DISTINCT FROM c.company_id "
            "    OR l.series IS DISTINCT FROM s.series "
            "    OR l.listed_on IS DISTINCT FROM s.listed_on)), "
            "u AS (UPDATE listings l SET company_id = t.new_cid, series = t.series, "
            "      listed_on = t.listed_on FROM t WHERE l.listing_id = t.listing_id "
            "      RETURNING l.listing_id) "
            "SELECT count(*) FILTER (WHERE t.relinked) AS n FROM t JOIN u USING (listing_id)"
        )
        linked = cur.fetchone()["n"]

        cur.execute(
            "INSERT INTO listings (company_id, exchange, symbol, kind, series, listed_on, "
            "is_active) "
            "SELECT c.company_id, 'NSE', s.symbol, 'equity', s.series, s.listed_on, false "
            "FROM _ref_nse s LEFT JOIN companies c ON c.isin = s.isin "
            "ON CONFLICT (exchange, symbol) DO NOTHING"
        )
        created = cur.rowcount

        cur.execute(
            "UPDATE listings b SET company_id = n.company_id "
            "FROM listings n "
            "WHERE b.exchange = 'BSE' AND b.kind = 'equity' AND b.symbol = ANY(%s) "
            "AND n.exchange = 'NSE' AND n.kind = 'equity' AND n.symbol = b.symbol "
            "AND n.company_id IS NOT NULL "
            "AND b.company_id IS NULL",
            (bse_symbols,),
        )
        linked += cur.rowcount

        cur.execute(
            "SELECT symbol FROM listings WHERE exchange = 'BSE' AND kind = 'equity' "
            "AND company_id IS NULL ORDER BY symbol"
        )
        unlinked = [f"BSE:{r['symbol']}" for r in cur.fetchall()]
        cur.execute("DROP TABLE _ref_nse")

    return SyncReport(companies, created, linked, unlinked)
