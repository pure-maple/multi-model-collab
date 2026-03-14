"""Tests for bugs found during DashScope cross-review (2026-03-07).

Bug 1+2: engine.py sequential mode convergence + double update
Bug 3: base.py generator return value capture
Bug 5: history.py metadata override
Bug 6: audit.py timezone handling
"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEngineSequentialConvergence:
    """Bug 1+2: Sequential mode should evaluate convergence and not double-update."""

    @pytest.mark.asyncio
    async def test_sequential_returns_turns(self):
        """_execute_round sequential should return turns, not empty list."""
        from vyane.a2a.engine import CollaborationEngine, EngineConfig
        from vyane.a2a.patterns import REVIEW_PATTERN
        from vyane.a2a.types import CollaborationTask, TaskState

        # Mock adapter
        mock_adapter = MagicMock()
        mock_result = MagicMock()
        mock_result.run_id = "test-001"
        mock_result.session_id = ""
        mock_result.output = "CONVERGED: all looks good"
        mock_result.summary = "all looks good"
        mock_result.status = "success"
        mock_result.error = None
        mock_adapter.run = AsyncMock(return_value=mock_result)

        engine = CollaborationEngine(
            get_adapter=lambda _: mock_adapter,
            config=EngineConfig(timeout_per_turn=10),
        )

        collab = CollaborationTask(
            goal="test",
            pattern="review",
            max_rounds=10,
        )
        collab.transition(TaskState.WORKING)

        from vyane.a2a.context import CollaborationContext
        ctx = CollaborationContext.from_task(collab)
        ctx.goal = "test"

        # Use a sequential round (implementer only)
        round_spec = REVIEW_PATTERN.rounds[0]  # implementer round
        role_providers = {"implementer": "codex", "reviewer": "gemini", "reviser": "codex"}

        turns = await engine._execute_round(
            collab=collab,
            ctx=ctx,
            pattern=REVIEW_PATTERN,
            round_spec=round_spec,
            role_providers=role_providers,
            round_num=1,
            iteration=1,
        )

        # Bug fix: should return turns, not empty list
        assert len(turns) > 0
        assert turns[0].output == "CONVERGED: all looks good"

    @pytest.mark.asyncio
    async def test_convergence_detected_in_sequential(self):
        """Full engine.run should detect convergence in sequential patterns."""
        from vyane.a2a.engine import CollaborationEngine, EngineConfig
        from vyane.a2a.types import TaskState

        mock_adapter = MagicMock()
        mock_result = MagicMock()
        mock_result.run_id = "test-001"
        mock_result.session_id = ""
        mock_result.output = "CONVERGED: implementation approved"
        mock_result.summary = "approved"
        mock_result.status = "success"
        mock_result.error = None
        mock_adapter.run = AsyncMock(return_value=mock_result)

        engine = CollaborationEngine(
            get_adapter=lambda _: mock_adapter,
            config=EngineConfig(timeout_per_turn=10),
        )

        collab = await engine.run(
            task="implement hello world",
            pattern_name="review",
        )

        # Should complete due to CONVERGED signal, not max iterations
        assert collab.state == TaskState.COMPLETED
        # Should NOT have run all max_iterations * rounds
        assert len(collab.turns) < 20


class TestGeneratorReturnValue:
    """Bug 3: Generator return value should be captured correctly."""

    def test_return_value_captured(self):
        """The exit code from stream_subprocess generator should be captured."""
        from vyane.adapters.base import stream_subprocess

        # We can't easily test with real subprocess, but verify the
        # while/next pattern captures StopIteration.value correctly
        def gen_with_return():
            yield "line1"
            yield "line2"
            return 42

        g = gen_with_return()
        lines = []
        exit_code = 0
        while True:
            try:
                line = next(g)
            except StopIteration as e:
                exit_code = e.value if e.value is not None else 0
                break
            lines.append(line)

        assert lines == ["line1", "line2"]
        assert exit_code == 42

    def test_none_return_defaults_to_zero(self):
        """Generator with no return statement should default to exit code 0."""
        def gen_no_return():
            yield "line1"

        g = gen_no_return()
        exit_code = -1
        while True:
            try:
                next(g)
            except StopIteration as e:
                exit_code = e.value if e.value is not None else 0
                break

        assert exit_code == 0

    def test_for_loop_loses_return(self):
        """Demonstrate that for-loop loses generator return value (the bug)."""
        def gen_with_return():
            yield "line1"
            return 42

        g = gen_with_return()
        for _ in g:
            pass

        # After for-loop exhausts generator, next() gives None value
        try:
            next(g)
        except StopIteration as e:
            # This is the bug: e.value is None, not 42
            assert e.value is None


class TestHistoryMetadataOverride:
    """Bug 5: result_dict should not override metadata fields."""

    def test_ts_not_overridden(self, tmp_path):
        from vyane.history import log_result

        history_file = tmp_path / "history.jsonl"
        with patch("vyane.history._history_file", return_value=history_file):
            log_result({"ts": 9999999999, "provider": "test"}, task="hello")

        entry = json.loads(history_file.read_text().strip())
        # ts should be current time, not the one from result_dict
        assert entry["ts"] != 9999999999
        assert entry["ts"] > time.time() - 10

    def test_source_not_overridden(self, tmp_path):
        from vyane.history import log_result

        history_file = tmp_path / "history.jsonl"
        with patch("vyane.history._history_file", return_value=history_file):
            log_result({"source": "hacked"}, task="hello", source="dispatch")

        entry = json.loads(history_file.read_text().strip())
        assert entry["source"] == "dispatch"

    def test_task_not_overridden(self, tmp_path):
        from vyane.history import log_result

        history_file = tmp_path / "history.jsonl"
        with patch("vyane.history._history_file", return_value=history_file):
            log_result({"task": "injected"}, task="real task")

        entry = json.loads(history_file.read_text().strip())
        assert entry["task"] == "real task"


class TestAuditTimezone:
    """Bug 6: Naive timestamps should be treated as UTC."""

    def test_naive_timestamp_treated_as_utc(self, tmp_path):
        from vyane.audit import AuditEntry, read_recent

        audit_file = tmp_path / "audit.jsonl"
        with patch("vyane.audit._audit_file", return_value=audit_file):
            # Write a naive ISO timestamp (no timezone info)
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            naive_ts = now_utc.replace(tzinfo=None).isoformat()
            entry = {"timestamp": naive_ts, "provider": "test", "status": "success"}
            audit_file.write_text(json.dumps(entry) + "\n")

            entries = read_recent(hours=1.0)

        assert len(entries) == 1
        assert entries[0].provider == "test"

    def test_aware_timestamp_works(self, tmp_path):
        from vyane.audit import read_recent

        audit_file = tmp_path / "audit.jsonl"
        with patch("vyane.audit._audit_file", return_value=audit_file):
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
            entry = {"timestamp": ts, "provider": "test", "status": "success"}
            audit_file.write_text(json.dumps(entry) + "\n")

            entries = read_recent(hours=1.0)

        assert len(entries) == 1

    def test_old_entry_filtered(self, tmp_path):
        from vyane.audit import read_recent

        audit_file = tmp_path / "audit.jsonl"
        with patch("vyane.audit._audit_file", return_value=audit_file):
            # Write an entry from 2 hours ago
            old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
            entry = {"timestamp": old.isoformat(), "provider": "test", "status": "success"}
            audit_file.write_text(json.dumps(entry) + "\n")

            entries = read_recent(hours=1.0)

        assert len(entries) == 0
