"""Result comparison for multi-model broadcast outputs.

Provides structural analysis of outputs from different providers:
- Word count and response time comparison
- Text similarity (Jaccard) between provider pairs
- Unique terms per provider
"""

from __future__ import annotations

import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    """Simple word tokenization (lowercase, alphanumeric only)."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity coefficient between two sets."""
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    return round(intersection / union, 3) if union > 0 else 0.0


def compare_results(results: list[dict]) -> dict:
    """Compare multiple provider results and generate analysis.

    Args:
        results: List of result dicts from mux_broadcast, each containing
            at least 'provider', 'status', 'output', 'duration_seconds'.

    Returns:
        Comparison dict with metrics, similarity, and per-provider analysis.
    """
    successful = [r for r in results if r.get("status") == "success"]

    if len(successful) < 2:
        return {"comparable": False, "reason": "Need at least 2 successful results"}

    # Per-provider metrics
    providers: dict[str, dict] = {}
    token_sets: dict[str, set] = {}

    for r in successful:
        prov = r.get("provider", "unknown")
        output = r.get("output", "")
        tokens = _tokenize(output)
        token_set = set(tokens)
        word_freq = Counter(tokens)

        providers[prov] = {
            "word_count": len(tokens),
            "char_count": len(output),
            "duration_seconds": r.get("duration_seconds", 0),
            "top_terms": [w for w, _ in word_freq.most_common(10)],
        }
        token_sets[prov] = token_set

    # Pairwise similarity
    prov_names = list(providers.keys())
    similarities: dict[str, float] = {}
    for i in range(len(prov_names)):
        for j in range(i + 1, len(prov_names)):
            a, b = prov_names[i], prov_names[j]
            sim = _jaccard(token_sets[a], token_sets[b])
            similarities[f"{a}_vs_{b}"] = sim

    # Overall agreement (average similarity)
    avg_sim = (
        round(sum(similarities.values()) / len(similarities), 3)
        if similarities
        else 0.0
    )

    # Unique terms per provider (appear in this provider but not others)
    all_tokens = set()
    for ts in token_sets.values():
        all_tokens |= ts

    unique_terms: dict[str, list[str]] = {}
    for prov, ts in token_sets.items():
        others = set()
        for other_prov, other_ts in token_sets.items():
            if other_prov != prov:
                others |= other_ts
        unique = ts - others
        # Top 10 unique terms by length (longer = more meaningful)
        unique_terms[prov] = sorted(unique, key=len, reverse=True)[:10]

    # Speed ranking
    speed_ranking = sorted(
        providers.keys(), key=lambda p: providers[p]["duration_seconds"]
    )

    return {
        "comparable": True,
        "provider_count": len(successful),
        "agreement_score": avg_sim,
        "pairwise_similarity": similarities,
        "speed_ranking": speed_ranking,
        "per_provider": providers,
        "unique_terms": unique_terms,
    }
