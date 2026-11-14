from datetime import date

from market_ingestion.instruments.events import parse_calendar

TODAY = date(2026, 11, 15)


def test_upcoming_results_and_dividend_with_amount():
    calendar = {
        "Earnings Date": [date(2027, 1, 13), date(2027, 1, 17)],
        "Earnings Average": 18.53185,
        "Ex-Dividend Date": date(2026, 11, 20),
    }
    asked = []

    def amount(d):
        asked.append(d)
        return 26.0

    assert parse_calendar(calendar, TODAY, amount) == [
        {
            "event_type": "results",
            "event_date": date(2027, 1, 13),
            "details": {"window_end": "2027-01-17", "eps_estimate": 18.53},
        },
        {
            "event_type": "ex_dividend",
            "event_date": date(2026, 11, 20),
            "details": {"amount": 26.0},
        },
    ]
    assert asked == [date(2026, 11, 20)]


def test_past_dates_and_empty_calendar_give_nothing():
    def never(d):
        raise AssertionError("dividend amount looked up for a past ex-date")

    past = {"Earnings Date": [date(2026, 10, 1)], "Ex-Dividend Date": date(2026, 6, 5)}
    assert parse_calendar(past, TODAY, never) == []
    assert parse_calendar({}, TODAY, never) == []
