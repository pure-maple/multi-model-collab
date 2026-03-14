"""Tests for structured intent classification (MER-88)."""

import json
import tempfile
import time
from pathlib import Path
from unittest import mock

from vyane.routing import (
    IntentCategory,
    IntentResult,
    classify_intent,
    classify_task,
)


# ── Each category classifies correctly for typical prompts ──


def test_code_gen():
    result = classify_intent("implement a REST API endpoint for user registration")
    assert result.primary == IntentCategory.CODE_GEN


def test_review():
    result = classify_intent("review this pull request for security issues")
    assert result.primary == IntentCategory.REVIEW


def test_analysis():
    result = classify_intent("analyze the performance bottleneck in the query layer")
    assert result.primary == IntentCategory.ANALYSIS


def test_debug():
    result = classify_intent("fix the crash that happens when user submits empty form")
    assert result.primary == IntentCategory.DEBUG


def test_docs():
    result = classify_intent("update the readme and add docstring for the authentication module")
    assert result.primary == IntentCategory.DOCS


def test_docs_translate():
    result = classify_intent("translate this release note into Chinese")
    assert result.primary == IntentCategory.DOCS


def test_docs_summarize():
    result = classify_intent("summarize this incident report")
    assert result.primary == IntentCategory.DOCS


def test_research():
    result = classify_intent("research alternatives to Redis for caching, compare pros and cons")
    assert result.primary == IntentCategory.RESEARCH


def test_refactor():
    result = classify_intent("refactor the payment module to extract shared logic")
    assert result.primary == IntentCategory.REFACTOR


def test_test():
    result = classify_intent("write unit test cases for the order service")
    assert result.primary == IntentCategory.TEST


# ── Confidence is higher when multiple signals match ──


def test_confidence_higher_with_more_signals():
    # Single signal
    single = classify_intent("implement something")
    # Multiple signals
    multi = classify_intent("implement and build a new function class endpoint")
    assert multi.confidence > single.confidence


# ── Ambiguous prompts return lower confidence ──


def test_ambiguous_lower_confidence():
    # Clear intent
    clear = classify_intent("implement a new REST API endpoint feature")
    # Ambiguous: review + code-gen signals
    ambiguous = classify_intent("review and implement the changes")
    assert clear.confidence > ambiguous.confidence


def test_no_match_zero_confidence():
    result = classify_intent("hello world")
    assert result.confidence == 0.0
    assert result.signals == []


# ── Secondary category is set for mixed-intent tasks ──


def test_secondary_category_set():
    result = classify_intent("review the code and fix any bugs you find")
    assert result.secondary is not None
    # Should have both review and debug signals
    categories = {result.primary, result.secondary}
    assert IntentCategory.REVIEW in categories or IntentCategory.DEBUG in categories


def test_secondary_none_for_single_category():
    result = classify_intent("hello world")
    assert result.secondary is None


# ── Signals list populated ──


def test_signals_populated():
    result = classify_intent("implement a REST API endpoint")
    assert len(result.signals) > 0
    assert any("implement" in s for s in result.signals)


# ── IntentCategory is a string enum ──


def test_intent_category_values():
    assert IntentCategory.CODE_GEN.value == "code-gen"
    assert IntentCategory.REVIEW.value == "review"
    assert IntentCategory.ANALYSIS.value == "analysis"
    assert IntentCategory.DEBUG.value == "debug"
    assert IntentCategory.DOCS.value == "docs"
    assert IntentCategory.RESEARCH.value == "research"
    assert IntentCategory.REFACTOR.value == "refactor"
    assert IntentCategory.TEST.value == "test"


# ── Backward compatibility: classify_task still works ──


def test_classify_task_backward_compat_generation():
    assert classify_task("implement a REST API endpoint") == "generation"


def test_classify_task_backward_compat_analysis():
    result = classify_task("review this code for security vulnerabilities")
    assert result == "analysis"


def test_classify_task_backward_compat_reasoning():
    result = classify_task("explain why this algorithm is O(n log n)")
    assert result == "reasoning"


def test_classify_task_backward_compat_reasoning_solve():
    result = classify_task("solve this puzzle and explain your logic")
    assert result == "reasoning"


def test_classify_task_backward_compat_language():
    result = classify_task("update the readme and changelog for the project")
    assert result == "language"


def test_classify_task_backward_compat_no_match():
    assert classify_task("hello") == ""


# ── Integration: classify_intent result is logged in history ──


def test_intent_logged_in_dispatch_result():
    """Verify that the intent dict structure is correct for logging."""
    intent = classify_intent("implement a new feature for the dashboard")
    # Simulate what server.py does
    result_dict: dict = {"provider": "codex", "status": "success"}
    result_dict["intent"] = {
        "category": intent.primary.value,
        "confidence": intent.confidence,
        "signals": intent.signals[:5],
    }

    assert "intent" in result_dict
    assert result_dict["intent"]["category"] == "code-gen"
    assert isinstance(result_dict["intent"]["confidence"], float)
    assert isinstance(result_dict["intent"]["signals"], list)
    # Should be JSON-serializable
    json.dumps(result_dict)


def test_intent_result_dataclass():
    """IntentResult dataclass fields are accessible."""
    result = IntentResult(
        primary=IntentCategory.DEBUG,
        confidence=0.85,
        secondary=IntentCategory.CODE_GEN,
        signals=["+fix", "bug"],
    )
    assert result.primary == IntentCategory.DEBUG
    assert result.confidence == 0.85
    assert result.secondary == IntentCategory.CODE_GEN
    assert len(result.signals) == 2
