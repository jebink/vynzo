"""sentiment job: the only I/O for news sentiment.

For every active equity company (NSE listing preferred, one per company) it fetches recent
headlines, scores them in batches through OpenRouter and upserts one SENTIMENT row per
listing for the run day into `signal`. The row's meta keeps the headlines that produced the
score. Re-running the same day replaces that day's rows. Companies without recent headlines
get a neutral row with confidence 0 and no model call.
"""

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from datetime import time as dtime

import psycopg
from psycopg.types.json import Jsonb

from analytics_worker.news import llm
from analytics_worker.news.sentiment import (
    CALC_VERSION,
    NO_NEWS,
    SIGNAL_TYPE,
    SYSTEM_PROMPT,
    Company,
    Score,
    build_prompt,
    parse_results,
    rationale,
    select_headlines,
)
from analytics_worker.news.sources import Headline, fetch_headlines
from analytics_worker.signals.high_volume_buy import UPSERT_SQL

log = logging.getLogger(__name__)

BATCH_SIZE = 10  # companies per model request: ~28 requests for 277 companies
PAUSE_S = 3.0  # between model requests (free models allow ~20 requests a minute)
FETCH_WORKERS = 4

# NSE listings first, so a company listed on both exchanges is scored once, on NSE.
COMPANIES_SQL = """
SELECT l.listing_id, l.company_id, l.symbol, l.exchange::text AS exchange, c.name,
       (SELECT o.close FROM ohlcv_latest o WHERE o.listing_id = l.listing_id) AS close
FROM listings l LEFT JOIN companies c USING (company_id)
WHERE l.is_active AND l.kind = 'equity'
  AND EXISTS (SELECT 1 FROM ohlcv_1d b WHERE b.listing_id = l.listing_id)
ORDER BY (l.exchange = 'NSE') DESC, l.listing_id
"""


@dataclass
class SentimentReport:
    as_of: str
    companies: int = 0
    with_news: int = 0
    no_news: int = 0
    scored: int = 0
    requests: int = 0
    quota_exhausted: bool = False
    labels: dict[str, int] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)


def _companies(conn: psycopg.Connection, limit: int | None) -> tuple[list[Company], dict]:
    rows = conn.execute(COMPANIES_SQL).fetchall()
    conn.commit()
    seen: set[int] = set()
    companies: list[Company] = []
    closes: dict[int, float | None] = {}
    for r in rows:
        if r["company_id"] is not None:
            if r["company_id"] in seen:
                continue
            seen.add(r["company_id"])
        companies.append(Company(r["listing_id"], r["symbol"], r["exchange"], r["name"]))
        closes[r["listing_id"]] = r["close"]
    return companies[:limit] if limit else companies, closes


def _row(
    company: Company,
    as_of: datetime,
    close: float | None,
    score: Score,
    headlines: list[Headline],
    model: str | None,
) -> dict:
    return {
        "listing_id": company.listing_id,
        "signal_type": SIGNAL_TYPE,
        "as_of": as_of,
        "strength": score.score,
        "price": close,
        "volume": None,
        "avg_volume": None,
        "rationale": rationale(score),
        "meta": Jsonb(
            {
                "label": score.label,
                "confidence": score.confidence,
                "summary": score.summary,
                "model": model,
                "headline_count": len(headlines),
                "sources": sorted({h.source for h in headlines}),
                "headlines": [h.as_json() for h in headlines],
            }
        ),
        "calc_version": CALC_VERSION,
    }


def _write(conn: psycopg.Connection, rows: list[dict]) -> None:
    if rows:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
    conn.commit()


def _score_batch(
    conn: psycopg.Connection,
    batch: list[tuple[Company, list[Headline]]],
    reply: dict,
    model: str,
    stamp: datetime,
    closes: dict[int, float | None],
    report: SentimentReport,
) -> None:
    """Write the batch's scores; companies the model skipped, or a failed write, go to failed."""
    scores = parse_results(reply, [c.symbol for c, _ in batch])
    rows, written = [], []
    for company, headlines in batch:
        score = scores.get(company.symbol.upper())
        if score is None:
            report.failed.append(company.symbol)
            continue
        rows.append(_row(company, stamp, closes[company.listing_id], score, headlines, model))
        written.append((company.symbol, score.label))
    try:
        _write(conn, rows)
    except psycopg.Error:
        conn.rollback()
        log.exception("writing batch %s failed", [s for s, _ in written])
        report.failed += [symbol for symbol, _ in written]
        return
    report.scored += len(written)
    for _, label in written:
        report.labels[label] = report.labels.get(label, 0) + 1
    report.models[model] = report.models.get(model, 0) + len(written)


def run_sentiment(
    conn: psycopg.Connection,
    *,
    api_key: str,
    model: str | None,
    as_of: date,
    limit: int | None = None,
    fetch: Callable[[str, str, str | None], list[Headline]] = fetch_headlines,
    chat: Callable[..., tuple[dict, str]] = llm.chat_json,
    list_models: Callable[[str | None], list[str]] = llm.candidate_models,
    pause_s: float = PAUSE_S,
) -> SentimentReport:
    report = SentimentReport(as_of=as_of.isoformat())
    stamp = datetime.combine(as_of, dtime(0), tzinfo=UTC)  # same convention as ohlcv_1d.ts
    now = datetime.now(UTC)
    companies, closes = _companies(conn, limit)
    report.companies = len(companies)

    def headlines_for(c: Company) -> list[Headline]:
        return select_headlines(fetch(c.symbol, c.exchange, c.name), now, c)

    with ThreadPoolExecutor(FETCH_WORKERS) as pool:
        found = list(zip(companies, pool.map(headlines_for, companies), strict=True))

    quiet = [c for c, h in found if not h]
    _write(conn, [_row(c, stamp, closes[c.listing_id], NO_NEWS, [], None) for c in quiet])
    report.no_news = len(quiet)
    if quiet:
        report.labels["neutral"] = len(quiet)

    newsy = [(c, h) for c, h in found if h]
    report.with_news = len(newsy)
    models = list_models(model) if newsy else []
    for start in range(0, len(newsy), BATCH_SIZE):
        batch = newsy[start : start + BATCH_SIZE]
        symbols = [c.symbol for c, _ in batch]
        if report.quota_exhausted:
            report.failed += symbols
            continue
        if report.requests:
            time.sleep(pause_s)
        report.requests += 1
        try:
            reply, used = chat(SYSTEM_PROMPT, build_prompt(batch), api_key=api_key, models=models)
        except llm.QuotaExhausted:
            log.exception("free model quota exhausted after %s requests", report.requests)
            report.quota_exhausted = True
            report.failed += symbols
            continue
        except llm.LLMError:
            log.exception("batch %s failed", symbols)
            report.failed += symbols
            continue
        # Rate-limited models stay so for a while: start the next batch with the one that answered.
        models = [used, *(m for m in models if m != used)]
        _score_batch(conn, batch, reply, used, stamp, closes, report)
    return report
