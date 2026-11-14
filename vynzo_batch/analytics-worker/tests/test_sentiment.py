"""News sentiment: feed parsing, headline selection, reply parsing and the job, all offline."""

from datetime import UTC, date, datetime, timedelta

import pytest
from analytics_worker.news import llm
from analytics_worker.news.job import BATCH_SIZE, run_sentiment
from analytics_worker.news.sentiment import (
    MAX_HEADLINES,
    NO_NEWS,
    Company,
    build_prompt,
    mentions,
    parse_results,
    select_headlines,
    to_score,
)
from analytics_worker.news.sources import (
    Headline,
    google_news_url,
    parse_google_rss,
    parse_yahoo_news,
    safe_url,
    short_name,
)

NOW = datetime(2026, 11, 14, 2, 0, tzinfo=UTC)

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>Adani Ports posts higher profit - Reuters</title>
<link>https://news.google.com/rss/articles/abc</link>
<pubDate>Thu, 12 Nov 2026 09:30:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Bad link item</title><link>javascript:alert(1)</link></item>
<item><title></title><link>https://x.test</link></item>
</channel></rss>"""


def _h(title, days_ago=1.0, source="google_news"):
    published = None if days_ago is None else NOW - timedelta(days=days_ago)
    return Headline(source, title, "https://x.test/a", "Pub", published)


# ---- sources ----


def test_parse_google_rss_strips_publisher_and_unsafe_links():
    items = parse_google_rss(RSS)
    assert [h.title for h in items] == ["Adani Ports posts higher profit", "Bad link item"]
    assert items[0].publisher == "Reuters"
    assert items[0].published == datetime(2026, 11, 12, 9, 30, tzinfo=UTC)
    assert items[1].url is None  # javascript: link dropped


def test_parse_yahoo_news_nested_and_flat():
    nested = {
        "content": {
            "title": "Infosys wins deal",
            "pubDate": "2026-11-13T05:00:00Z",
            "canonicalUrl": {"url": "https://finance.yahoo.com/n/1"},
            "provider": {"displayName": "Yahoo"},
        }
    }
    flat = {"title": "Old style", "link": "https://y.test/2", "providerPublishTime": 1_700_000_000}
    a, b = parse_yahoo_news([nested, flat, {"content": {}}])
    assert (a.title, a.url, a.publisher) == (
        "Infosys wins deal",
        "https://finance.yahoo.com/n/1",
        "Yahoo",
    )
    assert a.published == datetime(2026, 11, 13, 5, tzinfo=UTC)
    assert b.published is not None and b.url == "https://y.test/2"


@pytest.mark.parametrize(
    ("name", "short"),
    [
        ("Adani Enterprises Limited", "Adani Enterprises"),
        ("Tata Motors Ltd.", "Tata Motors"),
        ("Larsen & Toubro Limited", "Larsen & Toubro"),
        (None, None),
    ],
)
def test_short_name(name, short):
    assert short_name(name) == short


def test_google_news_url_searches_name_and_last_week():
    url = google_news_url("ADANIENT", "Adani Enterprises Limited")
    assert "%22Adani+Enterprises%22+OR+ADANIENT" in url and "when%3A7d" in url


def test_safe_url():
    assert safe_url(" https://a.test ") == "https://a.test"
    assert safe_url("javascript:alert(1)") is None
    assert safe_url(None) is None


# ---- selection and scoring ----


ADANI = Company(1, "ADANIENT", "NSE", "Adani Enterprises Limited")


def test_select_headlines_dedupes_drops_old_and_sorts_newest_first():
    picked = select_headlines(
        [
            _h("Adani profit rises", 2),
            _h("Adani profit rises!", 1, "yahoo_finance"),  # same headline, other source
            _h("Adani ancient news", 30),
            _h("ADANIENT undated", None),
            _h("Adani newest", 0.1),
        ],
        NOW,
        ADANI,
    )
    assert [h.title for h in picked] == ["Adani newest", "Adani profit rises", "ADANIENT undated"]


def test_select_headlines_keeps_only_news_about_the_company():
    picked = select_headlines(
        [
            _h("Reliance plans $4.6bn investment"),  # another company in the feed
            _h("Adani Enterprises Ltd (ADANIENT) Stock Price, News, Quote & History"),
            _h("Adani Enterprises arm inks MoU with Codelco"),
            _h("Why ADANIENT shares jumped"),
        ],
        NOW,
        ADANI,
    )
    assert [h.title for h in picked] == [
        "Adani Enterprises arm inks MoU with Codelco",
        "Why ADANIENT shares jumped",
    ]


@pytest.mark.parametrize(
    ("company", "title", "expected"),
    [
        (Company(1, "LT", "NSE", "Larsen & Toubro Limited"), "LT Foods share target", False),
        (Company(1, "LT", "NSE", "Larsen & Toubro Limited"), "Larsen wins order", True),
        (Company(1, "SBIN", "NSE", "State Bank of India"), "State govt cuts tax", False),
        (Company(1, "SBIN", "NSE", "State Bank of India"), "State Bank of India Q2 up", True),
        (Company(1, "TCS", "NSE", "Tata Consultancy Services Limited"), "TCS hires", True),
    ],
)
def test_mentions(company, title, expected):
    assert mentions(title, company) is expected


def test_select_headlines_caps():
    many = [_h(f"Adani story {i}", i / 10) for i in range(20)]
    assert len(select_headlines(many, NOW, ADANI)) == MAX_HEADLINES


def test_to_score_clamps_and_fixes_label():
    s = to_score({"score": 3, "label": "very good", "confidence": -1, "summary": " a\n b "})
    assert (s.score, s.label, s.confidence, s.summary) == (1.0, "bullish", 0.0, "a b")
    assert to_score({"score": "nan?"}).label == "neutral"
    assert to_score({"score": -0.5}).label == "bearish"


def test_parse_results_ignores_unknown_and_missing_symbols():
    reply = {
        "results": [
            {"symbol": "infy", "score": 0.4, "label": "bullish"},
            {"symbol": "HACKED", "score": 1},
            "junk",
        ]
    }
    scores = parse_results(reply, ["INFY", "TCS"])
    assert set(scores) == {"INFY"}


def test_build_prompt_lists_every_company():
    batch = [
        (Company(1, "INFY", "NSE", "Infosys Limited"), [_h("Deal win")]),
        (Company(2, "TCS", "NSE", None), [_h("Results")]),
    ]
    prompt = build_prompt(batch)
    assert "### INFY: Infosys Limited\n1. Deal win" in prompt
    assert "### TCS: TCS" in prompt and "all 2 symbols" in prompt


def test_extract_json_tolerates_fences_and_prose():
    assert llm.extract_json('```json\n{"results": []}\n```') == {"results": []}
    assert llm.extract_json('Sure! {"results": [1]} done') == {"results": [1]}
    with pytest.raises(llm.LLMError):
        llm.extract_json("no json here")


def test_free_json_models_keeps_free_json_capable_only():
    listed = [
        {"id": "a/x:free", "supported_parameters": ["response_format"]},
        {"id": "b/y:free", "supported_parameters": ["tools"]},  # no JSON mode
        {"id": "c/z", "supported_parameters": ["response_format"]},  # paid
        {"id": "d/w:free", "supported_parameters": ["structured_outputs"]},
    ]
    assert llm.free_json_models(listed) == ["a/x:free", "d/w:free"]


def test_order_models_prefers_configured_then_known_good_and_drops_unavailable():
    known = llm.FALLBACK_MODELS[1]
    ordered = llm.order_models("gone:free", ["other:free", known])
    assert ordered == [known, "other:free"]  # "gone" is not available today
    assert llm.order_models(None, None) == list(llm.FALLBACK_MODELS)[: llm.MAX_CANDIDATES]


# ---- job ----


class FakeConn:
    """Enough of psycopg for run_sentiment: one SELECT, upserts, commits."""

    def __init__(self, rows):
        self.rows = rows
        self.written: list[dict] = []

    def execute(self, _sql, *_a):
        rows = self.rows

        class Result:
            def fetchall(self):
                return rows

        return Result()

    def cursor(self):
        conn = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def executemany(self, _sql, rows):
                conn.written += list(rows)

        return Cursor()

    def commit(self):
        pass

    def rollback(self):
        pass


def _listing(i, company, symbol, exchange="NSE"):
    return {
        "listing_id": i,
        "company_id": company,
        "symbol": symbol,
        "exchange": exchange,
        "name": f"{symbol} Limited",
        "close": 100.0,
    }


def test_job_scores_dedupes_companies_and_stores_headlines():
    conn = FakeConn(
        [
            _listing(1, 10, "INFY"),
            _listing(2, 10, "INFY", "BSE"),  # same company on BSE: skipped
            _listing(3, 11, "QUIET"),
            _listing(4, 12, "MISSED"),
        ]
    )

    def fetch(symbol, _exchange, _name):
        return [] if symbol == "QUIET" else [_h(f"{symbol} news", 1)]

    def chat(_system, user, **_kw):
        assert "QUIET" not in user  # no model call for companies without news
        return {"results": [{"symbol": "INFY", "score": 0.6, "summary": "Good"}]}, "m:free"

    report = run_sentiment(
        conn,
        api_key="k",
        model=None,
        as_of=date(2026, 11, 14),
        fetch=fetch,
        chat=chat,
        list_models=lambda _m: ["m:free"],
    )
    assert (report.companies, report.with_news, report.no_news) == (3, 2, 1)
    assert report.scored == 1 and report.failed == ["MISSED"] and report.requests == 1
    by_id = {r["listing_id"]: r for r in conn.written}
    assert set(by_id) == {1, 3}
    infy = by_id[1]
    assert infy["as_of"] == datetime(2026, 11, 14, tzinfo=UTC)
    assert infy["strength"] == 0.6 and infy["signal_type"] == "SENTIMENT"
    meta = infy["meta"].obj
    assert meta["label"] == "bullish" and meta["model"] == "m:free"
    assert meta["headlines"][0]["title"] == "INFY news"
    assert by_id[3]["meta"].obj["summary"] == NO_NEWS.summary


def test_job_stops_calling_when_quota_is_spent():
    n = BATCH_SIZE * 2 + 1
    conn = FakeConn([_listing(i, i, f"S{i}") for i in range(n)])
    calls = 0

    def chat(*_a, **_kw):
        nonlocal calls
        calls += 1
        raise llm.QuotaExhausted("429")

    report = run_sentiment(
        conn,
        api_key="k",
        model=None,
        as_of=date(2026, 11, 14),
        fetch=lambda symbol, *_: [_h(f"{symbol} news", 1)],
        chat=chat,
        list_models=lambda _m: ["m:free"],
        pause_s=0,
    )
    assert calls == 1 and report.quota_exhausted
    assert len(report.failed) == n and conn.written == []


def test_job_starts_each_batch_with_the_model_that_last_answered():
    conn = FakeConn([_listing(i, i, f"S{i}") for i in range(BATCH_SIZE + 1)])
    seen: list[list[str]] = []

    def chat(_system, user, *, models, **_kw):
        seen.append(models)
        symbols = [line[4:].split(":")[0] for line in user.splitlines() if line.startswith("### ")]
        return {"results": [{"symbol": s, "score": 0} for s in symbols]}, "b:free"

    report = run_sentiment(
        conn,
        api_key="k",
        model=None,
        as_of=date(2026, 11, 14),
        fetch=lambda symbol, *_: [_h(f"{symbol} news", 1)],
        chat=chat,
        list_models=lambda _m: ["a:free", "b:free"],
        pause_s=0,
    )
    assert report.scored == BATCH_SIZE + 1
    assert seen == [["a:free", "b:free"], ["b:free", "a:free"]]
