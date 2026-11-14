"""Unit tests for the pure comparison helpers in scripts/parity_check.py."""

import importlib.util
from pathlib import Path

import numpy as np

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "parity_check.py"
_spec = importlib.util.spec_from_file_location("parity_check", _PATH)
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


def test_values_match_within_tolerance():
    assert pc.values_match(1.0, 1.0 + 1e-12)
    assert pc.values_match(1e9, 1e9 * (1 + 1e-10))
    assert not pc.values_match(1.0, 1.001)


def test_nan_and_none_match_each_other():
    assert pc.values_match(float("nan"), np.nan)
    assert pc.values_match(None, float("nan"))
    assert pc.values_match(None, None)


def test_nan_vs_value_mismatch():
    assert not pc.values_match(None, 1.0)
    assert not pc.values_match(1.0, float("nan"))


def test_recall_empty_legacy_is_one():
    assert pc.recall(set(), set()) == 1.0
    assert pc.recall(set(), {1, 2}) == 1.0


def test_recall_missed_legacy_hit_lowers_it():
    assert pc.recall({1, 2, 3, 4}, {1, 2, 3}) == 0.75
    assert pc.recall({1}, set()) == 0.0


def test_recall_ignores_new_only_hits():
    assert pc.recall({1, 2}, {1, 2, 3, 4, 5}) == 1.0
