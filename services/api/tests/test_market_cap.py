from app.modules.companies import market_cap


def test_market_cap_buckets_at_the_cut_offs():
    assert market_cap(10**9, 1000.0) == {"market_cap": 1e12, "cap_category": "large"}
    assert market_cap(10**9, 330.0)["cap_category"] == "mid"
    assert market_cap(10**9, 329.99)["cap_category"] == "small"


def test_market_cap_unknown_without_shares_or_price():
    unknown = {"market_cap": None, "cap_category": None}
    assert market_cap(None, 100.0) == unknown
    assert market_cap(0, 100.0) == unknown
    assert market_cap(10**6, None) == unknown
