from app.modules.stock_grading.scoring import SCORING_VERSION


def test_scoring_is_versioned():
    assert SCORING_VERSION
