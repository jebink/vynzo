import json
from dataclasses import dataclass

import pytest
from market_ingestion import __main__ as cli
from market_ingestion.__main__ import JOBS, main
from market_ingestion.pipeline import EodReport


def test_jobs_registered():
    assert set(JOBS) == {"eod", "backfill", "freshness", "sync-reference"}


def test_unknown_job_rejected():
    with pytest.raises(SystemExit):
        main(["no-such-job"])


@pytest.mark.parametrize(("failed", "code"), [(1, 0), (2, 0), (3, 1)])
def test_eod_exit_code_threshold(monkeypatch, capsys, failed, code):
    report = EodReport(listings=20, failed=[f"NSE:S{i}" for i in range(failed)], rows=5)
    monkeypatch.setattr(cli, "run_eod", lambda *a, **k: report)
    assert main(["eod"]) == code
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and json.loads(out[0])["listings"] == 20


def test_backfill_uses_configured_workers(monkeypatch, capsys):
    seen = {}

    def fake_backfill(*a, **k):
        seen.update(k)
        return EodReport(listings=0)

    monkeypatch.setattr(cli, "run_backfill", fake_backfill)
    monkeypatch.setenv("WORKERS", "7")
    assert main(["backfill"]) == 0
    assert seen["workers"] == 7
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_summary_is_one_json_line_with_iso_dates(capsys):
    from datetime import date

    @dataclass
    class S:
        d: date

    cli._emit(S(date(2026, 11, 5)))
    assert json.loads(capsys.readouterr().out) == {"d": "2026-11-05"}
