"""Tests for the mux_orchestrate MCP tool."""

import json
from unittest.mock import patch

import pytest

from modelmux.orchestrate_store import OrchestrateStore


class FakeRequestContext:
    """Minimal request context stub."""


class FakeContext:
    """Mock MCP Context with async methods."""

    def __init__(self):
        self._request_context = FakeRequestContext()
        self.session = None
        self.messages = []

    async def info(self, msg):
        self.messages.append(("info", msg))

    async def warning(self, msg):
        self.messages.append(("warning", msg))


class TestMuxOrchestrate:
    @pytest.mark.asyncio
    async def test_plan_assign_status_review_merge_flow(self, tmp_path):
        from modelmux.server import mux_orchestrate

        store = OrchestrateStore(path=tmp_path / "orchestrate.jsonl")
        ctx = FakeContext()

        with patch("modelmux.server._get_orchestrate_store", return_value=store):
            planned = json.loads(
                await mux_orchestrate(
                    action="plan", task="write release notes", ctx=ctx
                )
            )
            assert planned["status"] == "success"
            task_id = planned["task"]["task_id"]
            assert planned["task"]["suggested_role"] == "writer"

            assigned = json.loads(
                await mux_orchestrate(
                    action="assign",
                    task_id=task_id,
                    role="writer",
                    agent="claude",
                    branch="codex/notes",
                    ctx=ctx,
                )
            )
            assert assigned["task"]["state"] == "implementing"

            status = json.loads(
                await mux_orchestrate(action="status", task_id=task_id, ctx=ctx)
            )
            assert status["task"]["branch"] == "codex/notes"

            review = json.loads(
                await mux_orchestrate(action="review", branch="codex/notes", ctx=ctx)
            )
            assert review["task"]["state"] == "reviewing"

            merged = json.loads(
                await mux_orchestrate(action="merge", task_id=task_id, ctx=ctx)
            )
            assert merged["task"]["state"] == "integrated"

    @pytest.mark.asyncio
    async def test_status_summary_lists_tasks(self, tmp_path):
        from modelmux.server import mux_orchestrate

        store = OrchestrateStore(path=tmp_path / "orchestrate.jsonl")
        ctx = FakeContext()

        with patch("modelmux.server._get_orchestrate_store", return_value=store):
            await mux_orchestrate(action="plan", task="implement feature", ctx=ctx)
            await mux_orchestrate(action="plan", task="debug flaky test", ctx=ctx)

            result = json.loads(
                await mux_orchestrate(action="status", ctx=ctx, limit=5)
            )
            assert result["status"] == "success"
            assert result["summary"]["total"] == 2
            assert len(result["tasks"]) == 2
            assert "implementer" in result["roles"]

    @pytest.mark.asyncio
    async def test_plan_normalizes_task_id_before_duplicate_check(self, tmp_path):
        from modelmux.server import mux_orchestrate

        store = OrchestrateStore(path=tmp_path / "orchestrate.jsonl")
        ctx = FakeContext()

        with patch("modelmux.server._get_orchestrate_store", return_value=store):
            first = json.loads(
                await mux_orchestrate(
                    action="plan",
                    task="first task",
                    task_id="T001",
                    ctx=ctx,
                )
            )
            duplicate = json.loads(
                await mux_orchestrate(
                    action="plan",
                    task="replacement task",
                    task_id=" T001 ",
                    ctx=ctx,
                )
            )

        assert first["status"] == "success"
        assert duplicate["status"] == "error"
        assert "already exists" in duplicate["error"]

    @pytest.mark.asyncio
    async def test_task_id_lookup_does_not_fallback_to_branch(self, tmp_path):
        from modelmux.server import mux_orchestrate

        store = OrchestrateStore(path=tmp_path / "orchestrate.jsonl")
        ctx = FakeContext()

        with patch("modelmux.server._get_orchestrate_store", return_value=store):
            planned = json.loads(
                await mux_orchestrate(action="plan", task="implement feature", ctx=ctx)
            )
            task_id = planned["task"]["task_id"]
            await mux_orchestrate(
                action="assign",
                task_id=task_id,
                role="implementer",
                agent="codex",
                branch="codex/feature",
                ctx=ctx,
            )

            result = json.loads(
                await mux_orchestrate(
                    action="review",
                    task_id="T999",
                    branch="codex/feature",
                    ctx=ctx,
                )
            )

            status = json.loads(
                await mux_orchestrate(action="status", task_id=task_id, ctx=ctx)
            )

        assert result["status"] == "error"
        assert "Unknown task_id 'T999'" in result["error"]
        assert status["task"]["state"] == "implementing"

    @pytest.mark.asyncio
    async def test_task_id_and_branch_must_identify_the_same_task(self, tmp_path):
        from modelmux.server import mux_orchestrate

        store = OrchestrateStore(path=tmp_path / "orchestrate.jsonl")
        ctx = FakeContext()

        with patch("modelmux.server._get_orchestrate_store", return_value=store):
            first = json.loads(
                await mux_orchestrate(action="plan", task="first task", ctx=ctx)
            )
            second = json.loads(
                await mux_orchestrate(action="plan", task="second task", ctx=ctx)
            )

            await mux_orchestrate(
                action="assign",
                task_id=first["task"]["task_id"],
                role="implementer",
                agent="codex",
                branch="codex/one",
                ctx=ctx,
            )
            await mux_orchestrate(
                action="assign",
                task_id=second["task"]["task_id"],
                role="implementer",
                agent="codex",
                branch="codex/two",
                ctx=ctx,
            )

            result = json.loads(
                await mux_orchestrate(
                    action="review",
                    task_id=first["task"]["task_id"],
                    branch="codex/two",
                    ctx=ctx,
                )
            )

        assert result["status"] == "error"
        assert "task_id and branch refer to different tasks" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self, tmp_path):
        from modelmux.server import mux_orchestrate

        store = OrchestrateStore(path=tmp_path / "orchestrate.jsonl")
        ctx = FakeContext()

        with patch("modelmux.server._get_orchestrate_store", return_value=store):
            result = json.loads(await mux_orchestrate(action="ship", ctx=ctx))
        assert result["status"] == "error"
        assert "Unknown action" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_task_for_assign_returns_error(self, tmp_path):
        from modelmux.server import mux_orchestrate

        store = OrchestrateStore(path=tmp_path / "orchestrate.jsonl")
        ctx = FakeContext()

        with patch("modelmux.server._get_orchestrate_store", return_value=store):
            result = json.loads(
                await mux_orchestrate(
                    action="assign",
                    task_id="T999",
                    role="implementer",
                    agent="codex",
                    ctx=ctx,
                )
            )
        assert result["status"] == "error"
        assert "required" in result["error"] or "Unknown task_id" in result["error"]
