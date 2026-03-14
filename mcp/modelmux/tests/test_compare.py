"""Tests for the compare module (broadcast result comparison)."""

import pytest

from vyane.compare import _jaccard, _tokenize, compare_results


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("Hello World")
        assert tokens == ["hello", "world"]

    def test_removes_punctuation(self):
        tokens = _tokenize("def foo(): return bar")
        assert "foo" in tokens
        assert "return" in tokens
        assert "()" not in tokens

    def test_lowercase(self):
        tokens = _tokenize("CamelCase UPPER lower")
        assert all(t.islower() or t.isdigit() for t in tokens)

    def test_empty(self):
        assert _tokenize("") == []

    def test_numbers(self):
        tokens = _tokenize("version 3 point 14")
        assert "3" in tokens
        assert "14" in tokens


class TestJaccard:
    def test_identical_sets(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        sim = _jaccard({"a", "b", "c"}, {"b", "c", "d"})
        assert sim == pytest.approx(0.5, abs=0.01)

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 1.0

    def test_one_empty(self):
        assert _jaccard({"a"}, set()) == 0.0


class TestCompareResults:
    def test_not_enough_results(self):
        result = compare_results([{"status": "success", "output": "hello"}])
        assert result["comparable"] is False

    def test_all_failures(self):
        results = [
            {"provider": "a", "status": "error", "output": ""},
            {"provider": "b", "status": "error", "output": ""},
        ]
        result = compare_results(results)
        assert result["comparable"] is False

    def test_basic_comparison(self):
        results = [
            {
                "provider": "codex",
                "status": "success",
                "output": "The function should use a list comprehension",
                "duration_seconds": 5.0,
            },
            {
                "provider": "gemini",
                "status": "success",
                "output": "Use a list comprehension for better performance",
                "duration_seconds": 3.0,
            },
        ]
        result = compare_results(results)
        assert result["comparable"] is True
        assert result["provider_count"] == 2
        assert "agreement_score" in result
        assert result["agreement_score"] >= 0.0
        assert result["agreement_score"] <= 1.0
        assert "codex_vs_gemini" in result["pairwise_similarity"]

    def test_speed_ranking(self):
        results = [
            {"provider": "slow", "status": "success", "output": "hello", "duration_seconds": 10.0},
            {"provider": "fast", "status": "success", "output": "hello", "duration_seconds": 2.0},
            {"provider": "mid", "status": "success", "output": "hello", "duration_seconds": 5.0},
        ]
        result = compare_results(results)
        assert result["speed_ranking"][0] == "fast"
        assert result["speed_ranking"][-1] == "slow"

    def test_unique_terms(self):
        results = [
            {"provider": "a", "status": "success", "output": "python java rust", "duration_seconds": 1.0},
            {"provider": "b", "status": "success", "output": "python golang ruby", "duration_seconds": 1.0},
        ]
        result = compare_results(results)
        unique = result["unique_terms"]
        assert "java" in unique["a"] or "rust" in unique["a"]
        assert "golang" in unique["b"] or "ruby" in unique["b"]
        # python is shared, should not be in unique
        assert "python" not in unique["a"]
        assert "python" not in unique["b"]

    def test_per_provider_metrics(self):
        results = [
            {"provider": "x", "status": "success", "output": "hello world", "duration_seconds": 1.5},
            {"provider": "y", "status": "success", "output": "foo bar baz", "duration_seconds": 2.5},
        ]
        result = compare_results(results)
        assert result["per_provider"]["x"]["word_count"] == 2
        assert result["per_provider"]["y"]["word_count"] == 3
        assert result["per_provider"]["x"]["duration_seconds"] == 1.5

    def test_three_provider_comparison(self):
        results = [
            {"provider": "a", "status": "success", "output": "alpha beta gamma", "duration_seconds": 1.0},
            {"provider": "b", "status": "success", "output": "beta gamma delta", "duration_seconds": 2.0},
            {"provider": "c", "status": "success", "output": "gamma delta epsilon", "duration_seconds": 3.0},
        ]
        result = compare_results(results)
        assert result["provider_count"] == 3
        # Should have 3 pairs: a_vs_b, a_vs_c, b_vs_c
        assert len(result["pairwise_similarity"]) == 3

    def test_mixed_success_and_failure(self):
        results = [
            {"provider": "ok1", "status": "success", "output": "hello", "duration_seconds": 1.0},
            {"provider": "fail", "status": "error", "output": ""},
            {"provider": "ok2", "status": "success", "output": "hello", "duration_seconds": 2.0},
        ]
        result = compare_results(results)
        assert result["comparable"] is True
        assert result["provider_count"] == 2

    def test_identical_outputs(self):
        results = [
            {"provider": "a", "status": "success", "output": "same text", "duration_seconds": 1.0},
            {"provider": "b", "status": "success", "output": "same text", "duration_seconds": 1.0},
        ]
        result = compare_results(results)
        assert result["agreement_score"] == 1.0

    def test_top_terms_included(self):
        results = [
            {"provider": "a", "status": "success", "output": "the the the code code", "duration_seconds": 1.0},
            {"provider": "b", "status": "success", "output": "hello world", "duration_seconds": 1.0},
        ]
        result = compare_results(results)
        assert "the" in result["per_provider"]["a"]["top_terms"]
