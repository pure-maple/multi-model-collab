"""Dispatch result history for modelmux.

Stores complete dispatch results (including full output) in:
  ~/.config/modelmux/history.jsonl

Separate from audit.jsonl which only stores metadata for policy/rate-limiting.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _history_file() -> Path:
    return Path.home() / ".config" / "modelmux" / "history.jsonl"


def log_result(result_dict: dict, task: str = "", source: str = "dispatch") -> None:
    """Append a full dispatch result to the history log."""
    try:
        path = _history_file()
        path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            **result_dict,
            "ts": time.time(),
            "source": source,
            "task": task[:500],
        }

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Auto-rotate: cap at ~10MB
        _maybe_rotate(path)

        # Invalidate routing cache so next route sees new history
        try:
            from modelmux.routing import invalidate_routing_cache
            invalidate_routing_cache()
        except ImportError:
            pass
    except OSError:
        logger.debug("Failed to write history entry", exc_info=True)

    # Webhook notification (non-blocking, fire-and-forget)
    try:
        from modelmux.notifications import notify_dispatch

        notify_dispatch(result_dict, task=task, source=source)
    except Exception:
        logger.debug("Notification failed for %s dispatch", source, exc_info=True)


def _maybe_rotate(path: Path, max_bytes: int = 10 * 1024 * 1024) -> None:
    """Rotate history file if it exceeds max_bytes."""
    try:
        if path.stat().st_size > max_bytes:
            # Keep last half of the file
            lines = path.read_text(encoding="utf-8").splitlines()
            half = len(lines) // 2
            path.write_text("\n".join(lines[half:]) + "\n", encoding="utf-8")
    except OSError:
        pass


@dataclass
class HistoryQuery:
    """Query parameters for history search."""

    limit: int = 20
    provider: str = ""
    status: str = ""
    source: str = ""  # dispatch | broadcast
    hours: float = 0  # 0 = all time


def read_history(query: HistoryQuery | None = None) -> list[dict]:
    """Read history entries matching the query."""
    q = query or HistoryQuery()
    path = _history_file()
    if not path.exists():
        return []

    cutoff = time.time() - (q.hours * 3600) if q.hours > 0 else 0

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
                if q.provider and data.get("provider") != q.provider:
                    continue
                if q.status and data.get("status") != q.status:
                    continue
                if q.source and data.get("source") != q.source:
                    continue

                entries.append(data)
    except OSError:
        return []

    # Return most recent first, limited
    return entries[-q.limit :][::-1]


def get_trends(hours: float = 24, bucket_minutes: int = 60) -> dict:
    """Aggregate history into time-series buckets.

    Returns data suitable for charting: dispatch count, success rate,
    avg latency, and cumulative cost per time bucket.
    """
    path = _history_file()
    if not path.exists():
        return {"buckets": [], "hours": hours, "bucket_minutes": bucket_minutes}

    now = time.time()
    cutoff = now - (hours * 3600)
    bucket_secs = bucket_minutes * 60

    # Read all matching entries
    raw: list[dict] = []
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
                ts = data.get("ts", 0)
                if ts >= cutoff:
                    raw.append(data)
    except OSError:
        return {"buckets": [], "hours": hours, "bucket_minutes": bucket_minutes}

    if not raw:
        return {"buckets": [], "hours": hours, "bucket_minutes": bucket_minutes}

    # Build buckets from cutoff to now
    bucket_start = cutoff - (cutoff % bucket_secs)
    buckets_map: dict[float, dict] = {}
    t = bucket_start
    while t <= now:
        buckets_map[t] = {
            "ts": t,
            "count": 0,
            "success": 0,
            "error": 0,
            "total_duration": 0.0,
            "cost": 0.0,
            "by_provider": {},
        }
        t += bucket_secs

    # Fill buckets
    for entry in raw:
        ts = entry.get("ts", 0)
        bk = ts - (ts % bucket_secs)
        if bk not in buckets_map:
            continue
        b = buckets_map[bk]
        b["count"] += 1
        if entry.get("status") == "success":
            b["success"] += 1
        else:
            b["error"] += 1
        b["total_duration"] += entry.get("duration_seconds", 0)

        prov = entry.get("provider", "unknown")
        b["by_provider"][prov] = b["by_provider"].get(prov, 0) + 1

        # Cost from token usage
        usage = entry.get("token_usage")
        if usage:
            try:
                from modelmux.costs import estimate_cost

                est = estimate_cost(
                    prov,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    entry.get("model", ""),
                )
                b["cost"] += est.total_cost
            except Exception:
                logger.debug("Cost estimation failed for %s", prov, exc_info=True)

    # Convert to sorted list, compute derived fields
    sorted_keys = sorted(buckets_map.keys())
    result_buckets = []
    cumulative_cost = 0.0
    for k in sorted_keys:
        b = buckets_map[k]
        cumulative_cost += b["cost"]
        avg_dur = (
            round(b["total_duration"] / b["count"], 1) if b["count"] > 0 else 0
        )
        success_rate = (
            round(b["success"] / b["count"] * 100, 1) if b["count"] > 0 else 0
        )
        result_buckets.append(
            {
                "ts": b["ts"],
                "count": b["count"],
                "success": b["success"],
                "error": b["error"],
                "success_rate": success_rate,
                "avg_duration": avg_dur,
                "cost": round(b["cost"], 6),
                "cumulative_cost": round(cumulative_cost, 6),
                "by_provider": b["by_provider"],
            }
        )

    return {
        "buckets": result_buckets,
        "hours": hours,
        "bucket_minutes": bucket_minutes,
        "total_entries": len(raw),
    }


def get_history_stats(hours: float = 0, include_costs: bool = False) -> dict:
    """Compute aggregated stats from history."""
    path = _history_file()
    if not path.exists():
        return {"total": 0}

    cutoff = time.time() - (hours * 3600) if hours > 0 else 0

    total = 0
    providers: dict[str, dict] = {}
    sources: dict[str, int] = {}
    cost_entries: list[dict] = []

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

                total += 1
                src = data.get("source", "dispatch")
                sources[src] = sources.get(src, 0) + 1

                prov = data.get("provider", "unknown")
                if prov not in providers:
                    providers[prov] = {
                        "calls": 0,
                        "success": 0,
                        "error": 0,
                        "total_duration": 0.0,
                    }
                ps = providers[prov]
                ps["calls"] += 1
                if data.get("status") == "success":
                    ps["success"] += 1
                else:
                    ps["error"] += 1
                ps["total_duration"] += data.get("duration_seconds", 0)

                if include_costs and data.get("token_usage"):
                    cost_entries.append(data)
    except OSError:
        return {"total": 0}

    # Compute averages
    for ps in providers.values():
        if ps["calls"] > 0:
            ps["avg_duration"] = round(ps["total_duration"] / ps["calls"], 1)
            ps["success_rate"] = round(ps["success"] / ps["calls"] * 100, 1)
        del ps["total_duration"]

    result = {
        "total": total,
        "by_provider": providers,
        "by_source": sources,
        "file": str(path),
        "file_size_bytes": os.path.getsize(path) if path.exists() else 0,
    }

    if include_costs and cost_entries:
        from modelmux.costs import aggregate_costs

        result["costs"] = aggregate_costs(cost_entries)

    return result
