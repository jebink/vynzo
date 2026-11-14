#!/usr/bin/env python
"""Parity check: migrated bars + new code against legacy vinzo-core outputs. Read-only.

Indicators: for a seeded random sample of active listings, recompute compute_ta_frame over all
migrated 1d bars and compare with legacy.ta_daily for the last --window legacy dates.
HVB: re-evaluate the last --window sessions of every active listing; the gate is recall of the
legacy.signal HIGH_VOLUME_BUY rows in the same window (new-only hits are informational).

Exit 0 iff TA rate and HVB recall are >= --threshold. Last stdout line is a JSON summary.
"""

import argparse
import json
import math
import os
import random
import sys

import numpy as np
import pandas as pd
import psycopg
from analytics_worker.db import connect, load_daily_bars
from analytics_worker.indicators.ta import TA_COLUMNS, compute_ta_frame
from analytics_worker.signals.high_volume_buy import evaluate_at_index

MAX_LISTED = 20


def _is_null(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or bool(pd.isna(v))


def values_match(new, old, rtol: float = 1e-9, atol: float = 1e-9) -> bool:
    """True when both are null/NaN, or both are numbers that are close."""
    if _is_null(new) or _is_null(old):
        return _is_null(new) and _is_null(old)
    return bool(np.isclose(float(new), float(old), rtol=rtol, atol=atol))


def recall(legacy: set, new: set) -> float:
    """|legacy & new| / |legacy|, 1.0 when legacy is empty. New-only hits don't lower it."""
    return 1.0 if not legacy else len(legacy & new) / len(legacy)


def _legacy_present(conn) -> bool:
    return conn.execute("SELECT to_regnamespace('legacy') IS NOT NULL AS ok").fetchone()["ok"]


def check_indicators(conn, listings, window):
    compared = matched = used = 0
    mismatches: list[tuple] = []
    for lid, exch, sym in listings:
        bars = load_daily_bars(conn, lid)
        legacy = conn.execute(
            f"SELECT ts, {', '.join(TA_COLUMNS)} FROM legacy.ta_daily "
            "WHERE exchange = %s AND symbol = %s ORDER BY ts DESC LIMIT %s",
            (exch, sym, window),
        ).fetchall()
        if not legacy:
            continue
        used += 1
        frame = compute_ta_frame(bars) if not bars.empty else bars
        for row in legacy:
            ts = pd.Timestamp(row["ts"]).tz_convert("UTC")
            have = not frame.empty and ts in frame.index
            for col, old in ((c, row[c]) for c in TA_COLUMNS):
                compared += 1
                new = frame.at[ts, col] if have else None
                old = None if old is None else float(old)
                if have and values_match(new, old):
                    matched += 1
                elif len(mismatches) < MAX_LISTED:
                    mismatches.append((f"{exch}:{sym}", ts.date(), col, old, new))
    return compared, matched, mismatches, used


def check_hvb(conn, listing_rows, window):
    new_hits: set = set()
    starts: dict[int, pd.Timestamp] = {}
    for lid, _exch, _sym in listing_rows:
        df = load_daily_bars(conn, lid)
        if df.empty:
            continue
        first = max(0, len(df) - window)
        starts[lid] = df.index[first]
        for i in range(first, len(df)):
            if evaluate_at_index(df, i, lookback=20, multiplier=2.0) is not None:
                new_hits.add((lid, df.index[i]))
    rows = conn.execute(
        "SELECT li.listing_id, s.as_of FROM legacy.signal s "
        "JOIN listings li ON li.exchange = s.exchange AND li.symbol = s.symbol "
        "WHERE s.signal_type = 'HIGH_VOLUME_BUY'"
    ).fetchall()
    old_hits = {
        (lid, pd.Timestamp(ts).tz_convert("UTC"))
        for lid, ts in ((r["listing_id"], r["as_of"]) for r in rows)
        if lid in starts and pd.Timestamp(ts).tz_convert("UTC") >= starts[lid]
    }
    return new_hits, old_hits


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--sample", type=int, default=25)
    p.add_argument("--window", type=int, default=60)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--threshold", type=float, default=0.99)
    a = p.parse_args(argv)
    if not a.db:
        sys.exit("parity_check: pass --db or set DATABASE_URL")

    conn = connect(a.db)
    conn.autocommit = True  # read-only: SELECTs only
    if not _legacy_present(conn):
        sys.exit("parity_check: schema 'legacy' is missing; run it before the legacy drop")

    listings = [
        (r["listing_id"], r["exchange"], r["symbol"])
        for r in conn.execute(
            "SELECT l.listing_id, l.exchange, l.symbol FROM listings l WHERE l.is_active "
            "AND EXISTS (SELECT 1 FROM ohlcv_1d o WHERE o.listing_id = l.listing_id) "
            "ORDER BY l.listing_id"
        ).fetchall()
    ]
    sample = random.Random(a.seed).sample(listings, min(a.sample, len(listings)))

    compared, matched, mism, used = check_indicators(conn, sample, a.window)
    ta_rate = matched / compared if compared else 0.0
    print(f"Indicators: {used} of {len(sample)} sampled listings compared, window {a.window}")
    print(f"  compared={compared} matched={matched} rate={ta_rate:.6f}")
    for m in mism:
        print(f"  MISMATCH {m[0]} {m[1]} {m[2]} legacy={m[3]} new={m[4]}")

    new_hits, old_hits = check_hvb(conn, listings, a.window)
    hvb_recall = recall(old_hits, new_hits)
    new_only, legacy_only = new_hits - old_hits, old_hits - new_hits
    print(f"HVB: {len(listings)} listings, window {a.window}")
    print(
        f"  new={len(new_hits)} legacy={len(old_hits)} both={len(new_hits & old_hits)} "
        f"union={len(new_hits | old_hits)} recall={hvb_recall:.6f}"
    )
    if not old_hits:
        print("  legacy HVB hits: 0, recall gate is vacuous")
    print(f"  legacy-only (missed, failures): {len(legacy_only)}")
    for lid, ts in sorted(legacy_only)[:MAX_LISTED]:
        print(f"  DIFF legacy-only listing={lid} as_of={ts.date()}")
    print(f"  new-only (informational, legacy did not scan these; not a failure): {len(new_only)}")
    for lid, ts in sorted(new_only)[:MAX_LISTED]:
        print(f"  INFO new-only listing={lid} as_of={ts.date()}")

    ok = ta_rate >= a.threshold and hvb_recall >= a.threshold
    summary = {
        "ta_rate": ta_rate,
        "hvb_recall": hvb_recall,
        "hvb_new_only": len(new_only),
        "hvb_legacy_only": len(legacy_only),
        "pass": ok,
    }
    print(json.dumps(summary))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except psycopg.Error as e:
        sys.exit(f"parity_check: database error: {e}")
