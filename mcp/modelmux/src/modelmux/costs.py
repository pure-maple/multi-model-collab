"""Cost estimation for model API calls.

Provides approximate pricing per provider/model and cost calculation
from token usage data. Prices are in USD per million tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

# Pricing: USD per 1M tokens (input, output)
# Updated periodically — these are approximate reference prices.
PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "codex": {
        "default": (2.0, 8.0),
        "gpt-4.1": (2.0, 8.0),
        "gpt-4.1-mini": (0.4, 1.6),
        "gpt-4.1-nano": (0.1, 0.4),
        "gpt-5.4": (2.0, 8.0),
        "o3": (2.0, 8.0),
        "o4-mini": (1.1, 4.4),
    },
    "gemini": {
        "default": (1.25, 10.0),
        "gemini-2.5-pro": (1.25, 10.0),
        "gemini-2.5-flash": (0.15, 0.6),
        "gemini-3.1-pro-preview": (1.25, 10.0),
    },
    "claude": {
        "default": (3.0, 15.0),
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-opus-4-6": (15.0, 75.0),
        "claude-haiku-4-5": (0.8, 4.0),
    },
    "ollama": {
        "default": (0.0, 0.0),
    },
    "dashscope": {
        "default": (0.0, 0.0),  # Coding Plan: flat-rate subscription
        "qwen3-coder-plus": (0.0, 0.0),
        "qwen3-coder-next": (0.0, 0.0),
        "qwen3.5-plus": (0.0, 0.0),
        "qwen3-max-2026-01-23": (0.0, 0.0),
        "kimi-k2.5": (0.0, 0.0),
        "glm-5": (0.0, 0.0),
        "glm-4.7": (0.0, 0.0),
        "MiniMax-M2.5": (0.0, 0.0),
    },
}


@dataclass
class CostEstimate:
    """Estimated cost for a single API call."""

    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"
    model: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        d: dict = {
            "input_cost": round(self.input_cost, 6),
            "output_cost": round(self.output_cost, 6),
            "total_cost": round(self.total_cost, 6),
            "currency": self.currency,
        }
        if self.model:
            d["model"] = self.model
        if self.note:
            d["note"] = self.note
        return d


def estimate_cost(
    provider: str,
    input_tokens: int,
    output_tokens: int,
    model: str = "",
) -> CostEstimate:
    """Estimate cost based on provider, model, and token counts."""
    # Handle "provider/model" format (e.g. "dashscope/qwen3-coder-plus")
    base_provider = provider
    if "/" in provider:
        base_provider, embedded_model = provider.split("/", 1)
        if not model:
            model = embedded_model
    provider_pricing = PRICING.get(base_provider, {})
    if not provider_pricing:
        return CostEstimate(
            model=model,
            note=f"No pricing data for provider '{provider}'",
        )

    # Try exact model match, then default
    prices = provider_pricing.get(model) or provider_pricing.get("default")
    if not prices:
        return CostEstimate(
            model=model,
            note=f"No pricing data for model '{model}'",
        )

    input_price, output_price = prices
    input_cost = (input_tokens / 1_000_000) * input_price
    output_cost = (output_tokens / 1_000_000) * output_price

    return CostEstimate(
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=input_cost + output_cost,
        model=model or "default",
    )


def aggregate_costs(entries: list[dict]) -> dict:
    """Aggregate cost data from history entries.

    Each entry may have token_usage and provider fields.
    Returns totals by provider and overall.
    """
    by_provider: dict[str, dict] = {}
    total_input = 0
    total_output = 0
    total_cost = 0.0
    entries_with_usage = 0

    for entry in entries:
        usage = entry.get("token_usage")
        if not usage:
            continue

        entries_with_usage += 1
        provider = entry.get("provider", "unknown")
        model = entry.get("model", "")
        input_t = usage.get("input_tokens", 0)
        output_t = usage.get("output_tokens", 0)

        est = estimate_cost(provider, input_t, output_t, model)

        total_input += input_t
        total_output += output_t
        total_cost += est.total_cost

        if provider not in by_provider:
            by_provider[provider] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_cost": 0.0,
            }
        prov = by_provider[provider]
        prov["calls"] += 1
        prov["input_tokens"] += input_t
        prov["output_tokens"] += output_t
        prov["total_cost"] += est.total_cost

    # Round costs
    for prov in by_provider.values():
        prov["total_cost"] = round(prov["total_cost"], 6)

    return {
        "entries_with_usage": entries_with_usage,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 6),
        "by_provider": by_provider,
    }
