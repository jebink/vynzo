from datetime import date

from app.modules.fundamentals import repository, service


def test_industry_pe_falls_back_to_sector_when_industry_is_thin(monkeypatch):
    peers = {
        ("industry", "Aerospace"): [40.0, 50.0],
        ("sector", "Industrials"): [10.0, 30.0, 20.0, 60.0],
    }
    monkeypatch.setattr(repository, "peer_pes", lambda conn, col, val: peers.get((col, val), []))
    assert service.industry_pe(None, "Aerospace", "Industrials") == {
        "median": 25.0,
        "peers": 4,
        "basis": "sector",
        "group": "Industrials",
    }
    peers[("industry", "Aerospace")].append(45.0)
    assert service.industry_pe(None, "Aerospace", "Industrials")["basis"] == "industry"
    assert service.industry_pe(None, None, None) == {
        "median": None,
        "peers": 0,
        "basis": None,
        "group": None,
    }


def test_ttm_dividends_sums_payouts():
    rows = [
        {"ex_date": date(2026, 8, 13), "amount": 0.55},
        {"ex_date": date(2026, 3, 6), "amount": 1.95},
    ]
    assert service.ttm_dividends(rows) == 2.5
    assert service.ttm_dividends([]) is None


def _year(y, debt):
    return {"fiscal_year_end": date(y, 3, 31), "total_debt": debt}


def test_debt_cleared_from_peak_to_latest_year():
    d = service.debt_cleared(
        [_year(2023, 500.0), _year(2024, 800.0), _year(2025, 600.0), _year(2026, 200.0)]
    )
    assert d["peak_year_end"] == date(2024, 3, 31) and d["latest_year_end"] == date(2026, 3, 31)
    assert d["cleared"] == 600.0 and d["cleared_pct"] == 75.0


def test_debt_cleared_is_zero_at_a_new_peak_and_none_without_history():
    rising = service.debt_cleared([_year(2025, 100.0), _year(2026, 150.0)])
    assert rising["cleared"] == 0.0 and rising["peak_year_end"] == date(2026, 3, 31)
    assert service.debt_cleared([_year(2026, 100.0), _year(2025, None)]) is None
    assert service.debt_cleared([_year(2025, 0.0), _year(2026, 0.0)]) is None
