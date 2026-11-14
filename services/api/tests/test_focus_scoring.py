from datetime import date

from app.modules.focus import scoring

TODAY = date(2026, 11, 15)


def _row(closes, volumes, sentiment=None, news=None, event=(None, None)):
    return {
        "closes": closes,
        "volumes": volumes,
        "sentiment": sentiment,
        "news": news,
        "event_type": event[0],
        "event_date": event[1],
    }


def _calm(n=30):
    return [100 + (i % 2) * 0.5 for i in range(n)], [1_000_000.0] * n


def test_quiet_stock_scores_low_and_grades_d():
    closes, vols = _calm()
    f = scoring.focus(_row(closes, vols), TODAY)
    assert f.score < 10 and f.grade == "D"
    assert f.news.points == 0 and f.event.points == 0


def test_buzz_big_move_and_results_tomorrow_maxes_out():
    closes, vols = _calm()
    closes[-5:] = [104, 108, 112, 116, 120]  # +20% in 5 sessions against ~0.5% daily noise
    vols[-1] = 5_000_000.0
    news = {"headline_count": 8, "confidence": 1.0, "label": "bullish"}
    f = scoring.focus(_row(closes, vols, 1.0, news, ("results", date(2026, 11, 15))), TODAY)
    assert f.score == 100 and f.grade == "A"
    assert f.market.points == scoring.MARKET_MAX and f.event.points == scoring.EVENT_MAX
    assert "Quarterly results today" in f.event.reason


def test_negative_news_counts_like_positive_and_events_fade_with_distance():
    pos = scoring.news_part(0.8, {"headline_count": 4, "confidence": 0.5})
    neg = scoring.news_part(-0.8, {"headline_count": 4, "confidence": 0.5})
    assert pos.points == neg.points > 0
    near = scoring.event_part("results", date(2026, 11, 17), TODAY).points
    far = scoring.event_part("results", date(2026, 11, 28), TODAY).points
    assert near > far > 0


def test_grades():
    assert [scoring.grade(s) for s in (75, 74, 60, 45, 44)] == ["A", "B", "B", "C", "D"]
