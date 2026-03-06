"""Real-time dispatch status tracking.

Writes status files to ~/.config/modelmux/status/ for each active
dispatch. Enables external monitoring (TUI, tmux panes, dashboards)
to observe multi-model calls in progress.

Status files are automatically cleaned up after completion.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


def _status_dir() -> Path:
    return Path.home() / ".config" / "modelmux" / "status"


@dataclass
class DispatchStatus:
    """Real-time status of a single dispatch call."""

    run_id: str = ""
    provider: str = ""
    task_summary: str = ""
    status: str = "pending"  # pending | running | success | error | timeout
    started_at: float = 0.0
    elapsed_seconds: float = 0.0
    output_preview: str = ""
    output_lines: int = 0
    error: str = ""
    failover_from: str = ""


def write_status(status: DispatchStatus) -> None:
    """Write or update a dispatch status file."""
    try:
        d = _status_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{status.run_id}.json"
        path.write_text(
            json.dumps(asdict(status), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def remove_status(run_id: str) -> None:
    """Remove a completed dispatch status file."""
    try:
        path = _status_dir() / f"{run_id}.json"
        path.unlink(missing_ok=True)
    except OSError:
        pass


def list_active() -> list[DispatchStatus]:
    """List all currently active dispatch statuses."""
    d = _status_dir()
    if not d.exists():
        return []

    statuses: list[DispatchStatus] = []
    now = time.time()
    for path in d.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Skip stale entries (older than 10 minutes)
            started = data.get("started_at", 0)
            if started and (now - started) > 600:
                path.unlink(missing_ok=True)
                continue
            statuses.append(
                DispatchStatus(
                    **{
                        k: v
                        for k, v in data.items()
                        if k in DispatchStatus.__dataclass_fields__
                    }
                )
            )
        except (json.JSONDecodeError, OSError, TypeError):
            continue

    return sorted(statuses, key=lambda s: s.started_at)
