from datetime import date

from analytics_worker.news.orders import (
    CRORE,
    Candidate,
    build_prompt,
    looks_like_order,
    parse_orders,
)

BATCH = [
    Candidate(
        7,
        "BEL",
        "Bharat Electronics",
        [
            {
                "title": "BEL bags orders worth Rs 619 crore",
                "url": "u1",
                "published": "2026-11-12T10:00:00",
            },
            {"title": "BEL wins contract from Indian Army", "url": "u2", "published": None},
        ],
    )
]


def test_order_words_filter_headlines():
    assert looks_like_order("BEL bags orders worth Rs 619 crore")
    assert looks_like_order("L&T wins mega contract")
    assert not looks_like_order("BEL shares hit 52-week high")


def test_prompt_numbers_headlines_per_company():
    assert build_prompt(BATCH).splitlines() == [
        "## BEL (Bharat Electronics)",
        "1. BEL bags orders worth Rs 619 crore",
        "2. BEL wins contract from Indian Army",
    ]


def test_parse_orders_keeps_valid_items_and_drops_junk():
    reply = {
        "orders": [
            {
                "symbol": "bel",
                "headline": 1,
                "counterparty": None,
                "description": "Defence electronics",
                "value_crore": 619,
            },
            {
                "symbol": "BEL",
                "headline": 2,
                "counterparty": "Indian Army",
                "description": "Radars",
                "value_crore": "big",
            },
            {"symbol": "XYZ", "headline": 1, "description": "unknown symbol"},
            {"symbol": "BEL", "headline": 9, "description": "bad index"},
            {"symbol": "BEL", "headline": 1, "description": "  "},
            "junk",
        ]
    }
    rows = parse_orders(reply, BATCH, date(2026, 11, 15), "m")
    assert [r["source_url"] for r in rows] == ["u1", "u2"]
    assert rows[0]["value_inr"] == 619 * CRORE and rows[0]["reported_on"] == date(2026, 11, 12)
    assert rows[1]["value_inr"] is None and rows[1]["reported_on"] == date(2026, 11, 15)
    assert rows[1]["counterparty"] == "Indian Army" and rows[0]["company_id"] == 7
    assert parse_orders({}, BATCH, date(2026, 11, 15), "m") == []
