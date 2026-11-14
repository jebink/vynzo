"""orders job: orders, contracts and major projects pulled from the news headlines that the
sentiment job already stored (signal rows of type SENTIMENT keep their headlines in meta).

Only headlines that look like an order (ORDER_WORDS) go to the model, so most days need a few
requests. Each extracted order is stored once per (company, headline URL) in `company_order`.
Headline-based, so incomplete by nature: the exchange filing is the authoritative source.
"""

import json
import logging
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import psycopg

from analytics_worker.news import llm

log = logging.getLogger(__name__)

BATCH_SIZE = 8  # companies per model request
PAUSE_S = 3.0
CRORE = 1e7
ORDER_WORDS = re.compile(
    r"\b(orders?|contracts?|bags?|bagged|wins?|won|secures?|secured|bags|award(ed|s)?|"
    r"LoA|LoI|tender|project|deal|supply|MoU|agreement|partnership)\b",
    re.IGNORECASE,
)

_HEADLINES = """
SELECT DISTINCT ON (l.company_id) l.company_id, l.symbol, c.name, s.as_of,
       s.meta->'headlines' AS headlines
FROM signal s JOIN listings l USING (listing_id) LEFT JOIN companies c USING (company_id)
WHERE s.signal_type = 'SENTIMENT' AND s.as_of >= %(since)s AND l.company_id IS NOT NULL
  AND jsonb_array_length(coalesce(s.meta->'headlines', '[]'::jsonb)) > 0
ORDER BY l.company_id, s.as_of DESC
"""
_KNOWN = "SELECT company_id, source_url FROM company_order WHERE reported_on >= %(since)s - 30"
_INSERT = """
INSERT INTO company_order (company_id, reported_on, counterparty, description, value_inr,
                           source_url, headline, model)
VALUES (%(company_id)s, %(reported_on)s, %(counterparty)s, %(description)s, %(value_inr)s,
        %(source_url)s, %(headline)s, %(model)s)
ON CONFLICT (company_id, source_url) DO NOTHING
"""

SYSTEM_PROMPT = """You extract business orders from news headlines about Indian listed companies.

An order is a contract, purchase order, letter of award (LoA/LoI), tender win, supply deal or a
major project the company itself has won, received or started. Not orders: analyst views, price
targets, results, stake changes, dividends, general partnerships with no work awarded, or orders
placed BY the company with someone else unless it is a major capex project of its own.

Reply with JSON only:
{"orders": [{"symbol": "...", "headline": <headline number>, "counterparty": "who awarded it or
null", "description": "what the order is for, under 15 words", "value_crore": <INR crore as a
number, or null if not stated>}]}
Convert stated values to INR crore (1 lakh crore = 100000 crore; USD at 1 USD = 85 INR).
Return {"orders": []} when no headline is an order."""


@dataclass(frozen=True)
class Candidate:
    company_id: int
    symbol: str
    name: str | None
    headlines: list[dict[str, Any]]  # each: title, url, published (ISO or None)


@dataclass
class OrdersReport:
    as_of: str
    companies: int = 0
    candidates: int = 0
    requests: int = 0
    found: int = 0
    stored: int = 0
    quota_exhausted: bool = False
    failed: list[str] = field(default_factory=list)


def looks_like_order(title: str) -> bool:
    return bool(ORDER_WORDS.search(title or ""))


def build_prompt(batch: list[Candidate]) -> str:
    lines = []
    for c in batch:
        lines.append(f"## {c.symbol} ({c.name or c.symbol})")
        lines += [f"{i}. {h['title']}" for i, h in enumerate(c.headlines, start=1)]
    return "\n".join(lines)


def _day(published: str | None, fallback: date) -> date:
    try:
        return datetime.fromisoformat(published).date() if published else fallback
    except ValueError:
        return fallback


def parse_orders(reply: dict, batch: list[Candidate], as_of: date, model: str) -> list[dict]:
    """Valid orders from a model reply; unknown symbols, bad headline numbers and junk dropped."""
    by_symbol = {c.symbol.upper(): c for c in batch}
    out = []
    for item in reply.get("orders") or []:
        if not isinstance(item, dict):
            continue
        c = by_symbol.get(str(item.get("symbol", "")).upper())
        index = item.get("headline")
        if c is None or not isinstance(index, int) or not 1 <= index <= len(c.headlines):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        value = item.get("value_crore")
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        value = float(value) if ok and math.isfinite(value) and value > 0 else None
        h = c.headlines[index - 1]
        counterparty = item.get("counterparty")
        out.append(
            {
                "company_id": c.company_id,
                "reported_on": _day(h.get("published"), as_of),
                "counterparty": str(counterparty).strip()[:200] if counterparty else None,
                "description": description[:300],
                "value_inr": value * CRORE if value else None,
                "source_url": h["url"],
                "headline": h["title"],
                "model": model,
            }
        )
    return out


def candidates(conn: psycopg.Connection, since: date) -> tuple[int, list[Candidate]]:
    """(companies with headlines, those with order-like headlines not yet processed)."""
    known = {(r["company_id"], r["source_url"]) for r in conn.execute(_KNOWN, {"since": since})}
    rows = conn.execute(_HEADLINES, {"since": since}).fetchall()
    out = []
    for r in rows:
        heads = [
            h
            for h in (r["headlines"] or [])
            if isinstance(h, dict)  # older rows stored plain strings
            and h.get("url")
            and looks_like_order(h.get("title", ""))
            and (r["company_id"], h["url"]) not in known
        ]
        if heads:
            out.append(Candidate(r["company_id"], r["symbol"], r["name"], heads))
    return len(rows), out


def run_orders(
    conn: psycopg.Connection,
    *,
    api_key: str,
    model: str | None,
    as_of: date,
    since: date,
    chat: Callable[..., tuple[dict, str]] = llm.chat_json,
    list_models: Callable[[str | None], list[str]] = llm.candidate_models,
    pause_s: float = PAUSE_S,
) -> OrdersReport:
    report = OrdersReport(as_of=as_of.isoformat())
    report.companies, todo = candidates(conn, since)
    conn.commit()
    report.candidates = len(todo)
    models = list_models(model) if todo else []
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start : start + BATCH_SIZE]
        symbols = [c.symbol for c in batch]
        if report.quota_exhausted:
            report.failed += symbols
            continue
        if report.requests:
            time.sleep(pause_s)
        report.requests += 1
        try:
            reply, used = chat(SYSTEM_PROMPT, build_prompt(batch), api_key=api_key, models=models)
        except llm.QuotaExhausted:
            log.exception("free model quota exhausted")
            report.quota_exhausted = True
            report.failed += symbols
            continue
        except llm.LLMError:
            log.exception("orders batch %s failed", symbols)
            report.failed += symbols
            continue
        models = [used, *(m for m in models if m != used)]
        rows = parse_orders(reply, batch, as_of, used)
        report.found += len(rows)
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(_INSERT, row)
                report.stored += cur.rowcount
        conn.commit()
        log.debug("batch %s: %s", symbols, json.dumps(reply)[:500])
    return report
