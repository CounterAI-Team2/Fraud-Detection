"""
Fuzzy and exact name matching for sanctions screening.

Uses token-sorted ratio (order-independent) with a shared-token pre-filter so
batch screening across thousands of customers stays practical.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

FUZZY_THRESHOLD = 0.85
EXACT_THRESHOLD = 0.98

_MATCH_NONE = {
    "matched": False,
    "match_type": "none",
    "confidence": 0.0,
    "matched_name": "",
    "list_key": None,
    "query_name": "",
    "requires_confirmation": False,
}


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def token_sort_ratio(left: str, right: str) -> float:
    """Order-independent similarity in [0, 1]."""
    a = " ".join(sorted(normalize_name(left).split()))
    b = " ".join(sorted(normalize_name(right).split()))
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _shares_token(left: str, right: str) -> bool:
    left_tokens = set(normalize_name(left).split())
    right_tokens = set(normalize_name(right).split())
    return bool(left_tokens & right_tokens)


def classify_match_score(score: float) -> str:
    if score >= EXACT_THRESHOLD:
        return "exact"
    if score >= FUZZY_THRESHOLD:
        return "fuzzy"
    return "none"


def find_best_name_match(
    query: str,
    candidates: frozenset[str] | set[str],
    *,
    list_key_resolver=None,
) -> dict:
    """
    Return the best sanctions match for ``query`` against ``candidates``.

    ``list_key_resolver`` is an optional callable ``(matched_name) -> list_key``.
    """
    normalized_query = normalize_name(query)
    if not normalized_query:
        return {**_MATCH_NONE, "query_name": query}

    if normalized_query in candidates:
        matched_name = normalized_query
        list_key = list_key_resolver(matched_name) if list_key_resolver else None
        return {
            "matched": True,
            "match_type": "exact",
            "confidence": 1.0,
            "matched_name": matched_name,
            "list_key": list_key or "MAS Sanctions",
            "query_name": query,
            "requires_confirmation": False,
        }

    best_score = 0.0
    best_name = ""
    for candidate in candidates:
        if not _shares_token(normalized_query, candidate):
            continue
        score = token_sort_ratio(normalized_query, candidate)
        if score > best_score:
            best_score = score
            best_name = candidate

    match_type = classify_match_score(best_score)
    if match_type == "none":
        return {**_MATCH_NONE, "query_name": query}

    list_key = list_key_resolver(best_name) if list_key_resolver else None
    return {
        "matched": True,
        "match_type": match_type,
        "confidence": round(best_score, 4),
        "matched_name": best_name,
        "list_key": list_key or "MAS Sanctions",
        "query_name": query,
        "requires_confirmation": match_type == "fuzzy",
    }
