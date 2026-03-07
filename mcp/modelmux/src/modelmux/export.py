"""Export dispatch history to CSV, JSON, or Markdown reports.

Usage:
    modelmux export --format csv --hours 24
    modelmux export --format json --provider codex
    modelmux export --format md --hours 168 --output report.md
"""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from modelmux.history import HistoryQuery, get_history_stats, read_history


def export_csv(entries: list[dict]) -> str:
    """Export history entries as CSV."""
    buf = io.StringIO()
    fields = [
        "timestamp",
        "provider",
        "status",
        "duration_seconds",
        "task",
        "source",
        "input_tokens",
        "output_tokens",
        "model",
        "run_id",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for e in entries:
        usage = e.get("token_usage", {}) or {}
        row = {
            "timestamp": _format_ts(e.get("ts", 0)),
            "provider": e.get("provider", ""),
            "status": e.get("status", ""),
            "duration_seconds": e.get("duration_seconds", ""),
            "task": e.get("task", "")[:200],
            "source": e.get("source", ""),
            "input_tokens": usage.get("input_tokens", ""),
            "output_tokens": usage.get("output_tokens", ""),
            "model": e.get("model", ""),
            "run_id": e.get("run_id", ""),
        }
        writer.writerow(row)
    return buf.getvalue()


def export_json(entries: list[dict], stats: dict | None = None) -> str:
    """Export history entries as formatted JSON."""
    data: dict = {"exported_at": _format_ts(time.time()), "count": len(entries)}
    if stats:
        data["statistics"] = stats
    data["entries"] = entries
    return json.dumps(data, indent=2, ensure_ascii=False)


def export_markdown(
    entries: list[dict], stats: dict | None = None, title: str = "modelmux Report"
) -> str:
    """Export history as a Markdown report."""
    lines = [f"# {title}", ""]

    # Summary section
    if stats:
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Total dispatches**: {stats.get('total', 0)}")
        by_src = stats.get("by_source", {})
        if by_src:
            parts = [f"{k}: {v}" for k, v in by_src.items()]
            lines.append(f"- **By source**: {', '.join(parts)}")
        lines.append("")

        # Provider breakdown table
        by_prov = stats.get("by_provider", {})
        if by_prov:
            lines.append("## Provider Breakdown")
            lines.append("")
            lines.append("| Provider | Calls | Success Rate | Avg Duration |")
            lines.append("|----------|-------|-------------|-------------|")
            for prov, ps in by_prov.items():
                lines.append(
                    f"| {prov} | {ps.get('calls', 0)} | "
                    f"{ps.get('success_rate', 0)}% | "
                    f"{ps.get('avg_duration', 0)}s |"
                )
            lines.append("")

        # Cost section
        costs = stats.get("costs")
        if costs and costs.get("entries_with_usage", 0) > 0:
            lines.append("## Cost Summary")
            lines.append("")
            lines.append(f"- **Total cost**: ${costs.get('total_cost_usd', 0):.4f}")
            lines.append(
                f"- **Total tokens**: "
                f"{costs.get('total_input_tokens', 0):,} in / "
                f"{costs.get('total_output_tokens', 0):,} out"
            )
            lines.append("")

    # History table
    if entries:
        lines.append("## Recent Dispatches")
        lines.append("")
        lines.append("| Time | Provider | Status | Duration | Task |")
        lines.append("|------|----------|--------|----------|------|")
        for e in entries[:50]:  # Cap at 50 rows for readability
            ts = _format_ts(e.get("ts", 0))
            prov = e.get("provider", "?")
            st = e.get("status", "?")
            dur = f"{e.get('duration_seconds', 0):.1f}s"
            task = e.get("task", "")[:60]
            lines.append(f"| {ts} | {prov} | {st} | {dur} | {task} |")
        lines.append("")

    lines.append(f"*Generated at {_format_ts(time.time())}*")
    return "\n".join(lines)


def run_export(
    fmt: str = "csv",
    hours: float = 0,
    provider: str = "",
    limit: int = 1000,
    output: str = "",
    include_stats: bool = True,
    source: str = "",
) -> str:
    """Run export and return the content string (optionally write to file)."""
    query = HistoryQuery(limit=limit, provider=provider, hours=hours, source=source)
    entries = read_history(query)

    stats = None
    if include_stats:
        stats = get_history_stats(hours=hours, include_costs=True)

    if fmt == "csv":
        content = export_csv(entries)
    elif fmt == "json":
        content = export_json(entries, stats)
    elif fmt in ("md", "markdown"):
        content = export_markdown(entries, stats)
    else:
        raise ValueError(f"Unknown format: {fmt!r}. Use csv, json, or md.")

    if output:
        Path(output).write_text(content, encoding="utf-8")

    return content


def _format_ts(ts: float) -> str:
    """Format a unix timestamp as ISO 8601."""
    if not ts:
        return "?"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
