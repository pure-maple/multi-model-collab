"""Audit logging for modelmux dispatch calls.

Every mux_dispatch call is recorded as a JSONL entry in:
  ~/.config/modelmux/audit.jsonl

This provides a tamper-evident trail for debugging, cost tracking,
and policy enforcement (rate limiting reads from this log).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _audit_dir() -> Path:
    return Path.home() / ".config" / "modelmux"


def _audit_file() -> Path:
    return _audit_dir() / "audit.jsonl"


@dataclass
class AuditEntry:
    """A single audit log entry."""

    timestamp: str = ""
    provider: str = ""
    task_summary: str = ""
    status: str = ""
    duration_seconds: float = 0.0
    caller: str = ""
    caller_platform: str = ""
    routed_from: str = ""
    profile: str = ""
    sandbox: str = ""
    model: str = ""
    session_id: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)


def log_dispatch(entry: AuditEntry) -> None:
    """Append an audit entry to the JSONL log file."""
    try:
        d = _audit_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(_audit_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    except OSError:
        pass  # Never let audit logging break dispatch


def read_recent(hours: float = 1.0) -> list[AuditEntry]:
    """Read audit entries from the last N hours.

    Used by the policy engine for rate limiting.
    """
    cutoff = time.time() - (hours * 3600)
    entries: list[AuditEntry] = []

    path = _audit_file()
    if not path.exists():
        return entries

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    ts_str = data.get("timestamp", "")
                    # Parse ISO timestamp to epoch
                    if ts_str:
                        import datetime

                        dt = datetime.datetime.fromisoformat(ts_str)
                        if dt.timestamp() >= cutoff:
                            entries.append(
                                AuditEntry(
                                    **{
                                        k: v
                                        for k, v in data.items()
                                        if k in AuditEntry.__dataclass_fields__
                                    }
                                )
                            )
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except OSError:
        pass

    return entries


def count_recent(hours: float = 1.0) -> int:
    """Count dispatch calls in the last N hours."""
    return len(read_recent(hours))


def get_audit_stats() -> dict:
    """Get summary stats from the audit log."""
    path = _audit_file()
    if not path.exists():
        return {"total_entries": 0, "file_size_bytes": 0}

    total = 0
    providers: dict[str, int] = {}
    statuses: dict[str, int] = {}

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    total += 1
                    p = data.get("provider", "unknown")
                    providers[p] = providers.get(p, 0) + 1
                    s = data.get("status", "unknown")
                    statuses[s] = statuses.get(s, 0) + 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass

    return {
        "total_entries": total,
        "file_size_bytes": path.stat().st_size if path.exists() else 0,
        "by_provider": providers,
        "by_status": statuses,
        "audit_file": str(path),
    }
