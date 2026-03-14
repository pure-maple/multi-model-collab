"""Smart routing v4 — keyword + history + benchmark + user feedback.

Four-signal routing:
  1. Keyword patterns: match task text against provider-specific patterns
  2. History performance: success rate + latency from dispatch history
  3. Benchmark quality: per-category quality scores from benchmark results
  4. User feedback: aggregated user ratings from feedback.jsonl

Intent classification maps incoming prompts to structured categories
(code-gen, review, analysis, debug, docs, research, refactor, test)
for category-aware routing and logging.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── TTL cache for file-backed data ──
# Avoids re-reading history.jsonl / benchmark.json / feedback.jsonl
# on every smart_route() call. Cache entries expire after TTL seconds.

_CACHE_TTL = 60  # seconds

_cache: dict[str, tuple[float, Any]] = {}


def _get_cached(key: str) -> Any | None:
    """Return cached value if still valid, else None."""
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.time() - ts > _CACHE_TTL:
        del _cache[key]
        return None
    return value


def _set_cached(key: str, value: Any) -> None:
    """Store value in cache with current timestamp."""
    _cache[key] = (time.time(), value)


def invalidate_routing_cache() -> None:
    """Clear routing caches. Call after dispatches or feedback."""
    _cache.clear()


# Keyword patterns (same as server.py, extracted here for reuse)
_ROUTE_PATTERNS: dict[str, list[re.Pattern]] = {
    "gemini": [
        re.compile(
            r"\b(frontend|ui|ux|css|html|react|vue|svelte|angular|tailwind|"
            r"component|layout|responsive|style|theme|dashboard|"
            r"page|widget|modal|button|form|animation|figma|"
            r"visual|color|font|icon|image|illustration)\b",
            re.I,
        ),
    ],
    "codex": [
        re.compile(
            r"\b(implement|algorithm|backend|api|endpoint|database|sql|"
            r"debug|fix|bug|optimize|refactor|function|class|test|"
            r"server|middleware|auth|crud|migration|schema|query|"
            r"sort|search|tree|graph|linked.?list|hash|cache)\b",
            re.I,
        ),
    ],
    "claude": [
        re.compile(
            r"\b(architect|design.?pattern|review|analyze|explain|"
            r"trade.?off|compare|evaluate|plan|strategy|"
            r"security|audit|vulnerabilit|threat|"
            r"documentation|spec|rfc|adr|critique)\b",
            re.I,
        ),
    ],
    "dashscope": [
        re.compile(
            r"\b(qwen|tongyi|通义|千问|kimi|glm|智谱|minimax|"
            r"chinese|中文|翻译|translate.+chinese|"
            r"dashscope|阿里|alibaba)\b",
            re.I,
        ),
    ],
}

# Task category classifier patterns
_CATEGORY_PATTERNS: dict[str, re.Pattern] = {
    "analysis": re.compile(
        r"\b(review|audit|analyze|check|inspect|critique|evaluate|"
        r"security|vulnerability|bug|issue|improve|refactor)\b",
        re.I,
    ),
    "generation": re.compile(
        r"\b(write|create|implement|build|generate|add|make|"
        r"function|class|module|api|endpoint|component)\b",
        re.I,
    ),
    "reasoning": re.compile(
        r"\b(solve|explain|why|how|reason|logic|puzzle|"
        r"algorithm|proof|deduce|infer|compare|trade.?off)\b",
        re.I,
    ),
    "language": re.compile(
        r"\b(translate|summarize|rewrite|rephrase|document|"
        r"readme|changelog|comment|description|中文|chinese)\b",
        re.I,
    ),
}

# ── Structured intent classification ──


class IntentCategory(str, Enum):
    """Structured intent categories for task classification."""

    CODE_GEN = "code-gen"
    REVIEW = "review"
    ANALYSIS = "analysis"
    DEBUG = "debug"
    DOCS = "docs"
    RESEARCH = "research"
    REFACTOR = "refactor"
    TEST = "test"


@dataclass
class IntentResult:
    """Result of intent classification with confidence and debug signals."""

    primary: IntentCategory
    confidence: float  # 0.0–1.0
    secondary: IntentCategory | None = None
    signals: list[str] = field(default_factory=list)


# Primary keywords (weight 3) and secondary keywords (weight 1) per category.
_INTENT_KEYWORDS: dict[IntentCategory, tuple[list[str], list[str]]] = {
    IntentCategory.CODE_GEN: (
        # primary
        ["implement", "create", "write", "build", "add", "scaffold", "generate"],
        # secondary
        [
            "function",
            "class",
            "endpoint",
            "feature",
            "module",
            "api",
            "component",
            "make",
            "construct",
            "set up",
            "wire up",
        ],
    ),
    IntentCategory.REVIEW: (
        ["review", "audit", "inspect", "evaluate", "assess", "critique", "approve"],
        ["check", "examine", "look at", "code review", "pr review", "pull request"],
    ),
    IntentCategory.ANALYSIS: (
        ["analyze", "explain", "investigate", "understand", "trace", "profile"],
        [
            "why does",
            "how does",
            "what causes",
            "root cause",
            "deep dive",
            "break down",
            "walk through",
        ],
    ),
    IntentCategory.DEBUG: (
        ["fix", "debug", "troubleshoot", "diagnose"],
        [
            "bug",
            "error",
            "crash",
            "broken",
            "failing",
            "not working",
            "issue",
            "exception",
            "stack trace",
            "segfault",
        ],
    ),
    IntentCategory.DOCS: (
        ["document", "readme", "docstring", "changelog", "api docs", "wiki"],
        ["comment", "jsdoc", "typedoc", "description", "annotation", "documentation"],
    ),
    IntentCategory.RESEARCH: (
        ["research", "compare", "explore", "benchmark"],
        [
            "alternatives",
            "options",
            "pros and cons",
            "trade-off",
            "trade off",
            "survey",
            "landscape",
            "evaluation",
            "spike",
        ],
    ),
    IntentCategory.REFACTOR: (
        ["refactor", "restructure", "reorganize", "deduplicate"],
        [
            "clean up",
            "simplify",
            "extract",
            "optimize",
            "consolidate",
            "rename",
            "move",
            "split",
        ],
    ),
    IntentCategory.TEST: (
        ["unit test", "integration test", "test plan", "test suite"],
        [
            "test",
            "spec",
            "coverage",
            "assertion",
            "mock",
            "fixture",
            "expect",
            "pytest",
            "jest",
            "vitest",
        ],
    ),
}

# Map IntentCategory → legacy benchmark category strings for backward compat.
_INTENT_TO_BENCHMARK_CATEGORY: dict[IntentCategory, str] = {
    IntentCategory.CODE_GEN: "generation",
    IntentCategory.REVIEW: "analysis",
    IntentCategory.ANALYSIS: "reasoning",
    IntentCategory.DEBUG: "analysis",
    IntentCategory.DOCS: "language",
    IntentCategory.RESEARCH: "reasoning",
    IntentCategory.REFACTOR: "generation",
    IntentCategory.TEST: "generation",
}

_PRIMARY_WEIGHT = 3
_SECONDARY_WEIGHT = 1


def classify_intent(task: str) -> IntentResult:
    """Classify a task into a structured intent category.

    Uses weighted keyword matching: primary keywords score higher than
    secondary keywords. Returns the best-matching category with a
    confidence score based on score margin over the runner-up.
    """
    task_lower = task.lower()
    scores: dict[IntentCategory, float] = {}
    matched_signals: dict[IntentCategory, list[str]] = {}

    for cat, (primary_kws, secondary_kws) in _INTENT_KEYWORDS.items():
        total = 0.0
        signals: list[str] = []

        for kw in primary_kws:
            if kw in task_lower:
                total += _PRIMARY_WEIGHT
                signals.append(f"+{kw}")

        for kw in secondary_kws:
            if kw in task_lower:
                total += _SECONDARY_WEIGHT
                signals.append(kw)

        if total > 0:
            scores[cat] = total
            matched_signals[cat] = signals

    if not scores:
        # No matches — default to CODE_GEN with zero confidence
        return IntentResult(
            primary=IntentCategory.CODE_GEN,
            confidence=0.0,
            signals=[],
        )

    # Sort categories by score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_cat, best_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0

    # Confidence: how dominant is the top score?
    # - If only one category matched, high confidence
    # - If top score >> runner-up, high confidence
    # - If scores are close, lower confidence
    if runner_up_score == 0:
        confidence = min(1.0, best_score / (_PRIMARY_WEIGHT * 2))
    else:
        margin = (best_score - runner_up_score) / best_score
        base_confidence = min(1.0, best_score / (_PRIMARY_WEIGHT * 2))
        confidence = base_confidence * (0.5 + 0.5 * margin)

    confidence = round(confidence, 3)

    secondary = ranked[1][0] if len(ranked) > 1 else None

    return IntentResult(
        primary=best_cat,
        confidence=confidence,
        secondary=secondary,
        signals=matched_signals.get(best_cat, []),
    )


# Weight for combining keyword, history, benchmark, and feedback scores
KEYWORD_WEIGHT = 0.35
HISTORY_WEIGHT = 0.25
BENCHMARK_WEIGHT = 0.20
FEEDBACK_WEIGHT = 0.20

# How many hours of history to consider
HISTORY_WINDOW_HOURS = 72

# Default benchmark results path
_BENCHMARK_FILE = Path.home() / ".config" / "modelmux" / "benchmark.json"


@dataclass
class ProviderScore:
    """Routing score breakdown for a single provider."""

    provider: str
    keyword_score: float = 0.0
    success_rate: float = 0.5  # default neutral
    latency_score: float = 0.5  # default neutral
    benchmark_score: float = 0.5  # default neutral
    feedback_score: float = 0.5  # default neutral
    history_calls: int = 0
    feedback_count: int = 0
    task_category: str = ""
    composite: float = 0.0


def keyword_scores(task: str, providers: list[str] | None = None) -> dict[str, float]:
    """Score providers by keyword pattern matching.

    Returns normalized scores (0.0–1.0) per provider.
    """
    raw: dict[str, int] = {}
    for provider, patterns in _ROUTE_PATTERNS.items():
        if providers and provider not in providers:
            continue
        raw[provider] = sum(len(p.findall(task)) for p in patterns)

    # Include any requested providers not in patterns
    if providers:
        for p in providers:
            if p not in raw:
                raw[p] = 0

    max_score = max(raw.values()) if raw else 1
    if max_score == 0:
        # No keywords matched — equal chance for all
        return {p: 0.5 for p in raw}

    return {p: s / max_score for p, s in raw.items()}


def _read_history_stats(hours: float = HISTORY_WINDOW_HOURS) -> dict[str, dict]:
    """Read per-provider stats from history.jsonl directly.

    Returns {provider: {calls, success, total_duration}} without
    importing history module (avoids circular deps).
    Results are cached for _CACHE_TTL seconds.
    """
    cache_key = f"history_stats_{hours}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    path = Path.home() / ".config" / "modelmux" / "history.jsonl"
    if not path.exists():
        return {}

    cutoff = time.time() - (hours * 3600) if hours > 0 else 0
    providers: dict[str, dict] = {}

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue

                # Skip broadcasts/workflows — only use dispatch results
                if data.get("source") != "dispatch":
                    continue
                if cutoff and data.get("ts", 0) < cutoff:
                    continue

                prov = data.get("provider", "")
                if not prov:
                    continue

                if prov not in providers:
                    providers[prov] = {
                        "calls": 0,
                        "success": 0,
                        "total_duration": 0.0,
                    }

                ps = providers[prov]
                ps["calls"] += 1
                if data.get("status") == "success":
                    ps["success"] += 1
                ps["total_duration"] += data.get("duration_seconds", 0)
    except OSError:
        return {}

    _set_cached(cache_key, providers)
    return providers


def history_scores(
    providers: list[str],
    hours: float = HISTORY_WINDOW_HOURS,
) -> dict[str, ProviderScore]:
    """Score providers based on historical dispatch performance.

    Returns ProviderScore with success_rate and latency_score filled in.
    Providers with no history get neutral scores (0.5).
    """
    stats = _read_history_stats(hours)

    # Compute latency averages for normalization
    avg_latencies: dict[str, float] = {}
    for prov in providers:
        ps = stats.get(prov)
        if ps and ps["calls"] > 0:
            avg_latencies[prov] = ps["total_duration"] / ps["calls"]

    max_latency = max(avg_latencies.values()) if avg_latencies else 1.0
    if max_latency == 0:
        max_latency = 1.0

    scores: dict[str, ProviderScore] = {}
    for prov in providers:
        ps = stats.get(prov)
        score = ProviderScore(provider=prov)

        if ps and ps["calls"] >= 2:
            # Need at least 2 calls for meaningful stats
            score.history_calls = ps["calls"]
            score.success_rate = ps["success"] / ps["calls"]
            # Latency: lower is better → invert
            avg_lat = ps["total_duration"] / ps["calls"]
            score.latency_score = 1.0 - (avg_lat / max_latency) * 0.5
        else:
            # Not enough data — neutral
            score.success_rate = 0.5
            score.latency_score = 0.5
            score.history_calls = ps["calls"] if ps else 0

        scores[prov] = score

    return scores


def classify_task(task: str) -> str:
    """Classify a task into a benchmark category (backward-compatible wrapper).

    Returns one of: "analysis", "generation", "reasoning", "language", or ""
    (empty if no clear match).

    Internally uses ``classify_intent()`` and maps the result to legacy
    benchmark category strings.
    """
    intent = classify_intent(task)
    if intent.confidence == 0.0:
        return ""
    return _INTENT_TO_BENCHMARK_CATEGORY.get(intent.primary, "")


def benchmark_scores(
    providers: list[str],
    category: str = "",
    benchmark_path: Path | None = None,
) -> dict[str, float]:
    """Load per-provider quality scores from saved benchmark results.

    If a category is specified, uses only results from that category.
    Returns {provider: quality_score} where quality_score is 0.0–1.0.
    Providers with no benchmark data get 0.5 (neutral).
    Results are cached for _CACHE_TTL seconds.
    """
    path = benchmark_path or _BENCHMARK_FILE

    # Cache raw benchmark results (file read is expensive, aggregation is cheap)
    cache_key = f"benchmark_raw_{path}"
    results = _get_cached(cache_key)
    if results is None:
        if not path.exists():
            return {p: 0.5 for p in providers}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {p: 0.5 for p in providers}
        results = data.get("results", [])
        if results:
            _set_cached(cache_key, results)

    if not results:
        return {p: 0.5 for p in providers}

    # Aggregate per-provider scores, optionally filtered by category
    provider_data: dict[str, dict] = {}
    for r in results:
        prov = r.get("provider", "")
        if prov not in providers:
            continue
        if category and r.get("category", "") != category:
            continue

        if prov not in provider_data:
            provider_data[prov] = {
                "total": 0,
                "success": 0,
                "kw_sum": 0.0,
                "kw_count": 0,
            }

        pd = provider_data[prov]
        pd["total"] += 1
        if r.get("status") == "success":
            pd["success"] += 1
        kw_total = r.get("keyword_total", 0)
        if kw_total > 0:
            pd["kw_sum"] += r.get("keyword_hits", 0) / kw_total
            pd["kw_count"] += 1

    scores: dict[str, float] = {}
    for p in providers:
        pd = provider_data.get(p)
        if not pd or pd["total"] == 0:
            scores[p] = 0.5
            continue

        # Blend success rate (60%) and keyword accuracy (40%)
        success_rate = pd["success"] / pd["total"]
        kw_score = pd["kw_sum"] / pd["kw_count"] if pd["kw_count"] > 0 else 0.5
        scores[p] = success_rate * 0.6 + kw_score * 0.4

    return scores


def smart_route(
    task: str,
    available_providers: list[str],
    excluded: list[str] | None = None,
    default: str = "codex",
) -> tuple[str, dict[str, ProviderScore]]:
    """Route a task using keyword + history composite scoring.

    Returns (best_provider, {provider: ProviderScore}).
    """
    excluded = excluded or []
    candidates = [p for p in available_providers if p not in excluded]

    if not candidates:
        return default, {}

    if len(candidates) == 1:
        return candidates[0], {
            candidates[0]: ProviderScore(provider=candidates[0], composite=1.0)
        }

    # 0. Task classification (structured intent)
    intent = classify_intent(task)
    category = _INTENT_TO_BENCHMARK_CATEGORY.get(intent.primary, "")

    # 1. Keyword scoring
    kw_scores = keyword_scores(task, candidates)

    # 2. History scoring
    hist_scores = history_scores(candidates)

    # 3. Benchmark quality scoring (category-aware)
    bench_scores = benchmark_scores(candidates, category=category)

    # 4. User feedback scoring (category-aware)
    from modelmux.feedback import feedback_scores as _feedback_scores

    fb_scores = _feedback_scores(candidates, category=category)

    # 5. Composite — four-signal blend
    for prov in candidates:
        hs = hist_scores[prov]
        hs.keyword_score = kw_scores.get(prov, 0.0)
        hs.benchmark_score = bench_scores.get(prov, 0.5)
        hs.feedback_score = fb_scores.get(prov, 0.5)
        hs.task_category = category

        # History component: blend success rate (70%) and latency (30%)
        history_component = hs.success_rate * 0.7 + hs.latency_score * 0.3

        # Check data availability for adaptive weighting
        has_bench = bench_scores.get(prov, 0.5) != 0.5
        has_feedback = fb_scores.get(prov, 0.5) != 0.5

        if hs.history_calls >= 5 and has_bench and has_feedback:
            # Full four-signal: keyword 35%, history 25%, benchmark 20%, feedback 20%
            weight_kw = KEYWORD_WEIGHT
            weight_hist = HISTORY_WEIGHT
            weight_bench = BENCHMARK_WEIGHT
            weight_fb = FEEDBACK_WEIGHT
        elif hs.history_calls >= 5 and has_bench:
            # Three-signal (no feedback)
            weight_kw = 0.40
            weight_hist = 0.30
            weight_bench = 0.30
            weight_fb = 0.0
        elif hs.history_calls >= 2:
            # History available, other signals partial
            weight_kw = 0.45
            weight_hist = 0.25
            weight_bench = 0.15 if has_bench else 0.0
            weight_fb = 0.15 if has_feedback else 0.0
            # Redistribute missing weight to keyword
            miss = 0.15 if not has_bench else 0.0
            miss += 0.15 if not has_feedback else 0.0
            weight_kw += miss
        else:
            # Minimal data — keyword-heavy
            weight_kw = 0.60
            weight_hist = 0.0
            weight_bench = 0.20 if has_bench else 0.0
            weight_fb = 0.20 if has_feedback else 0.0
            miss = 0.20 if not has_bench else 0.0
            miss += 0.20 if not has_feedback else 0.0
            weight_kw += miss

        hs.composite = (
            hs.keyword_score * weight_kw
            + history_component * weight_hist
            + hs.benchmark_score * weight_bench
            + hs.feedback_score * weight_fb
        )

    best = max(candidates, key=lambda p: hist_scores[p].composite)

    # If all composites are equal (e.g., no keywords, no history), use default
    scores_set = {round(hist_scores[p].composite, 4) for p in candidates}
    if len(scores_set) == 1 and default in candidates:
        best = default

    return best, hist_scores
