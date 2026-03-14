"""Real-time dispatch status tracking.

Writes status files to ~/.config/vyane/status/ for each active
dispatch. Enables external monitoring (TUI, tmux panes, dashboards)
to observe multi-model calls in progress.

If that directory is not present yet, Vyane falls back to:
  ~/.config/modelmux/status/

Status files are automatically cleaned up after completion.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from vyane.paths import resolve_user_write_path


def _status_dir() -> Path:
    return resolve_user_write_path("status")


@dataclass
class DispatchStatus:
    """Real-time status of a single dispatch call."""

    run_id: str = ""
    provider: str = ""
    task_summary: str = ""
    status: str = "pending"  # pending | running | success | error | timeout | cancelled
    started_at: float = 0.0
    elapsed_seconds: float = 0.0
    output_preview: str = ""
    output_lines: int = 0
    error: str = ""
    failover_from: str = ""
    async_mode: bool = False
    paused: bool = False
    result: dict | None = None


def _safe_filename(run_id: str) -> str:
    """Ensure run_id is safe for use as a filename (no path traversal)."""
    import re

    return re.sub(r"[^a-zA-Z0-9_-]", "", run_id)[:32]


def write_status(status: DispatchStatus) -> None:
    """Write or update a dispatch status file."""
    try:
        d = _status_dir()
        d.mkdir(parents=True, exist_ok=True)
        safe_id = _safe_filename(status.run_id)
        if not safe_id:
            return
        path = d / f"{safe_id}.json"
        path.write_text(
            json.dumps(asdict(status), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def remove_status(run_id: str) -> None:
    """Remove a completed dispatch status file."""
    try:
        safe_id = _safe_filename(run_id)
        if not safe_id:
            return
        path = _status_dir() / f"{safe_id}.json"
        path.unlink(missing_ok=True)
    except OSError:
        pass


def read_status(run_id: str) -> DispatchStatus | None:
    """Read status for a specific run_id. Returns None if not found."""
    try:
        safe_id = _safe_filename(run_id)
        if not safe_id:
            return None
        path = _status_dir() / f"{safe_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return DispatchStatus(
            **{
                k: v
                for k, v in data.items()
                if k in DispatchStatus.__dataclass_fields__
            }
        )
    except (json.JSONDecodeError, OSError, TypeError):
        return None


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
