"""Smart routing v2 — keyword patterns + historical performance scoring.

Combines the built-in keyword heuristics with data from dispatch history
(success rate, latency) to improve auto-routing accuracy over time.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

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
}

# Weight for combining keyword vs history scores
KEYWORD_WEIGHT = 0.6
HISTORY_WEIGHT = 0.4

# How many hours of history to consider
HISTORY_WINDOW_HOURS = 72


@dataclass
class ProviderScore:
    """Routing score breakdown for a single provider."""

    provider: str
    keyword_score: float = 0.0
    success_rate: float = 0.5  # default neutral
    latency_score: float = 0.5  # default neutral
    history_calls: int = 0
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
    """
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

    # 1. Keyword scoring
    kw_scores = keyword_scores(task, candidates)

    # 2. History scoring
    hist_scores = history_scores(candidates)

    # 3. Composite
    for prov in candidates:
        hs = hist_scores[prov]
        hs.keyword_score = kw_scores.get(prov, 0.0)

        # History component: blend success rate (70%) and latency (30%)
        history_component = hs.success_rate * 0.7 + hs.latency_score * 0.3

        # Has enough history data? Use full weight. Otherwise, lean on keywords.
        if hs.history_calls >= 5:
            weight_kw = KEYWORD_WEIGHT
            weight_hist = HISTORY_WEIGHT
        elif hs.history_calls >= 2:
            weight_kw = 0.75
            weight_hist = 0.25
        else:
            weight_kw = 1.0
            weight_hist = 0.0

        hs.composite = hs.keyword_score * weight_kw + history_component * weight_hist

    best = max(candidates, key=lambda p: hist_scores[p].composite)

    # If all composites are equal (e.g., no keywords, no history), use default
    scores_set = {round(hist_scores[p].composite, 4) for p in candidates}
    if len(scores_set) == 1 and default in candidates:
        best = default

    return best, hist_scores
