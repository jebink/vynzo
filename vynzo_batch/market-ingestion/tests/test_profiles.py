from market_ingestion.instruments.profiles import parse_info


def test_parse_info_reads_yahoo_fields():
    info = {"sharesOutstanding": 16336840, "sector": "Industrials", "industry": "Metal Fabrication"}
    assert parse_info(info) == {
        "sector": "Industrials",
        "industry": "Metal Fabrication",
        "shares": 16336840,
    }


def test_parse_info_falls_back_to_implied_shares_and_drops_junk():
    assert parse_info({"impliedSharesOutstanding": 5.0, "sector": ""}) == {
        "sector": None,
        "industry": None,
        "shares": 5,
    }
    assert parse_info({"sharesOutstanding": 0, "sector": None}) is None
    assert parse_info({}) is None
