from __future__ import annotations

from utils.name_matching import (
    EXACT_THRESHOLD,
    FUZZY_THRESHOLD,
    classify_match_score,
    find_best_name_match,
    normalize_name,
    token_sort_ratio,
)


def test_normalize_name_collapses_whitespace_and_uppercases():
    assert normalize_name("  mohammad   reza  zahedi ") == "MOHAMMAD REZA ZAHEDI"


def test_token_sort_ratio_is_order_independent():
    assert token_sort_ratio("Zahedi Mohammad Reza", "MOHAMMAD REZA ZAHEDI") == 1.0


def test_exact_match_by_normalized_equality():
    candidates = frozenset({"MOHAMMAD REZA ZAHEDI", "ABBAS RASHIDI"})
    result = find_best_name_match("mohammad reza zahedi", candidates)
    assert result["matched"] is True
    assert result["match_type"] == "exact"
    assert result["confidence"] == 1.0
    assert result["requires_confirmation"] is False


def test_fuzzy_match_requires_confirmation():
    candidates = frozenset({"MOHAMMAD REZA ZAHEDI"})
    result = find_best_name_match("Mohammad Reza Zahed", candidates)
    assert result["matched"] is True
    assert result["match_type"] == "fuzzy"
    assert result["confidence"] >= FUZZY_THRESHOLD
    assert result["confidence"] < EXACT_THRESHOLD
    assert result["requires_confirmation"] is True


def test_no_match_below_threshold():
    candidates = frozenset({"MOHAMMAD REZA ZAHEDI"})
    result = find_best_name_match("James Johnson", candidates)
    assert result["matched"] is False
    assert result["match_type"] == "none"


def test_classify_match_score_buckets():
    assert classify_match_score(1.0) == "exact"
    assert classify_match_score(EXACT_THRESHOLD) == "exact"
    assert classify_match_score(FUZZY_THRESHOLD) == "fuzzy"
    assert classify_match_score(0.5) == "none"
