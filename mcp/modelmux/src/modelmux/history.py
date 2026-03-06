"""Dispatch result history for modelmux.

Stores complete dispatch results (including full output) in:
  ~/.config/modelmux/history.jsonl

Separate from audit.jsonl which only stores metadata for policy/rate-limiting.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


def _history_file() -> Path:
    return Path.home() / ".config" / "modelmux" / "history.jsonl"


def log_result(result_dict: dict, task: str = "", source: str = "dispatch") -> None:
    """Append a full dispatch result to the history log."""
    try:
        path = _history_file()
        path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "ts": time.time(),
            "source": source,
            "task": task[:500],
            **result_dict,
        }

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Auto-rotate: cap at ~10MB
        _maybe_rotate(path)
    except OSError:
        pass

    # Webhook notification (non-blocking, fire-and-forget)
    try:
        from modelmux.notifications import notify_dispatch

        notify_dispatch(result_dict, task=task, source=source)
    except Exception:
        pass  # Never let notification failure affect core flow


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
