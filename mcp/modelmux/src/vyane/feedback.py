"""User feedback collection and scoring for routing.

Stores user ratings of dispatch results in:
  ~/.config/vyane/feedback.jsonl

If that file is not present yet, Vyane falls back to:
  ~/.config/modelmux/feedback.jsonl

Each feedback entry links to a dispatch run_id and includes:
  - rating: 1-5 (1=terrible, 5=excellent)
  - provider: which provider produced the result
  - category: task category (analysis/generation/reasoning/language)

Feedback scores are aggregated per provider and per category
to inform smart routing decisions.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from vyane.paths import resolve_user_write_path


def _feedback_file() -> Path:
    return resolve_user_write_path("feedback.jsonl")


def log_feedback(
    run_id: str,
    provider: str,
    rating: int,
    category: str = "",
    comment: str = "",
) -> None:
    """Record a user feedback entry."""
    if not 1 <= rating <= 5:
        raise ValueError(f"Rating must be 1-5, got {rating}")

    path = _feedback_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": time.time(),
        "run_id": run_id,
        "provider": provider,
        "rating": rating,
        "category": category,
    }
    if comment:
        entry["comment"] = comment

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Invalidate routing cache so next route sees new feedback
    try:
        from vyane.routing import invalidate_routing_cache

        invalidate_routing_cache()
    except ImportError:
        pass


def read_feedback(
    hours: float = 0,
    provider: str = "",
) -> list[dict]:
    """Read feedback entries, optionally filtered by time window and provider."""
    path = _feedback_file()
    if not path.exists():
        return []

    cutoff = time.time() - (hours * 3600) if hours > 0 else 0
    entries: list[dict] = []

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

                if cutoff and data.get("ts", 0) < cutoff:
                    continue
                if provider and data.get("provider", "") != provider:
                    continue

                entries.append(data)
    except OSError:
        return []

    return entries


def feedback_scores(
    providers: list[str],
    hours: float = 168,  # 1 week default
    category: str = "",
) -> dict[str, float]:
    """Compute per-provider feedback quality scores.

    Returns {provider: score} where score is 0.0-1.0.
    Score is normalized average rating (rating/5).
    Providers with no feedback get 0.5 (neutral).
    Uses routing cache for read_feedback to avoid repeated disk I/O.
    """
    from vyane.routing import _get_cached, _set_cached

    cache_key = f"feedback_entries_{hours}"
    entries = _get_cached(cache_key)
    if entries is None:
        entries = read_feedback(hours=hours)
        _set_cached(cache_key, entries)

    # Aggregate ratings per provider
    totals: dict[str, list[int]] = {p: [] for p in providers}

    for entry in entries:
        prov = entry.get("provider", "")
        if prov not in totals:
            continue
        if category and entry.get("category", "") != category:
            continue
        rating = entry.get("rating", 0)
        if 1 <= rating <= 5:
            totals[prov].append(rating)

    scores: dict[str, float] = {}
    for p in providers:
        ratings = totals[p]
        if len(ratings) >= 2:
            # Normalize average rating to 0.0-1.0
            scores[p] = sum(ratings) / (len(ratings) * 5)
        else:
            scores[p] = 0.5  # neutral for insufficient data

    return scores
