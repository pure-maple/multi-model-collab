"""JSONL persistence for mux_orchestrate tasks."""

from __future__ import annotations

import copy
import json
import re
from collections import OrderedDict
from pathlib import Path

from modelmux.orchestrate import OrchestratedTask


def _store_file() -> Path:
    return Path.home() / ".config" / "modelmux" / "orchestrate_tasks.jsonl"


class OrchestrateStore:
    """Append-only JSONL task store with latest-snapshot reads."""

    def __init__(self, path: Path | None = None, max_bytes: int = 5 * 1024 * 1024):
        self._path = path or _store_file()
        self._max_bytes = max_bytes
        self._tasks: dict[str, OrchestratedTask] = {}
        self._loaded = False

    def next_task_id(self) -> str:
        """Generate the next T### identifier."""
        self._ensure_loaded()
        current_max = 0
        for task_id in self._tasks:
            match = re.fullmatch(r"T(\d+)", task_id)
            if match:
                current_max = max(current_max, int(match.group(1)))
        return f"T{current_max + 1:03d}"

    def upsert(self, task: OrchestratedTask) -> OrchestratedTask:
        """Persist the latest snapshot for a task."""
        self._ensure_loaded()
        stored = copy.deepcopy(task)
        self._append_snapshot(stored)
        self._tasks[stored.task_id] = stored
        return copy.deepcopy(stored)

    def get(self, task_id: str) -> OrchestratedTask | None:
        """Fetch a single task by id."""
        self._ensure_loaded()
        task = self._tasks.get(task_id)
        return copy.deepcopy(task) if task else None

    def find_by_branch(self, branch: str) -> OrchestratedTask | None:
        """Fetch the most recent task associated with a branch."""
        self._ensure_loaded()
        matches = [task for task in self._tasks.values() if task.branch == branch]
        if not matches:
            return None
        latest = max(matches, key=lambda item: item.updated_at)
        return copy.deepcopy(latest)

    def list(self, limit: int = 20, state: str = "") -> list[OrchestratedTask]:
        """List tasks, newest first, with optional state filter."""
        self._ensure_loaded()
        items = sorted(
            self._tasks.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        if state:
            items = [item for item in items if item.state.value == state]
        return [copy.deepcopy(item) for item in items[:limit]]

    def state_counts(self) -> dict[str, int]:
        """Return a count of tasks per state."""
        self._ensure_loaded()
        counts: dict[str, int] = {}
        for task in self._tasks.values():
            counts[task.state.value] = counts.get(task.state.value, 0) + 1
        return counts

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as handle:
                    for line in handle:
                        task = self._load_snapshot(line)
                        if task is not None:
                            self._tasks[task.task_id] = task
            except OSError:
                pass

        self._loaded = True

    def _append_snapshot(self, task: OrchestratedTask) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(task.to_dict(), ensure_ascii=False) + "\n")
        try:
            # Rotation is best-effort after the snapshot has been durably appended.
            self._maybe_rotate()
        except OSError:
            pass

    def _maybe_rotate(self) -> None:
        if self._path.stat().st_size <= self._max_bytes:
            return

        latest_snapshots: OrderedDict[str, dict[str, object]] = OrderedDict()
        with open(self._path, encoding="utf-8") as handle:
            for line in handle:
                task = self._load_snapshot(line)
                if task is None:
                    continue
                if task.task_id in latest_snapshots:
                    del latest_snapshots[task.task_id]
                latest_snapshots[task.task_id] = task.to_dict()

        compacted = "\n".join(
            json.dumps(record, ensure_ascii=False)
            for record in latest_snapshots.values()
        )
        if compacted:
            compacted += "\n"

        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(compacted, encoding="utf-8")
        temp_path.replace(self._path)

    def _load_snapshot(self, line: str) -> OrchestratedTask | None:
        line = line.strip()
        if not line:
            return None

        try:
            record = json.loads(line)
            task = OrchestratedTask.from_dict(record)
        except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
            return None

        if not task.task_id:
            return None
        return task
