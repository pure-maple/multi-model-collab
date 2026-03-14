"""Tests for async intervention features (MER-86).

Covers pause/resume lifecycle, partial output streaming, task list,
and error handling for non-existent tasks.
"""

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from vyane.adapters.base import AdapterResult, BaseAdapter
from vyane.status import DispatchStatus, read_status, write_status


# --- Fake Context for testing MCP tools ---


class FakeRequestContext:
    """Minimal request context stub."""


class FakeContext:
    """Mock MCP Context with async methods."""

    def __init__(self):
        self._request_context = FakeRequestContext()
        self.session = None
        self._messages = []

    async def info(self, msg):
        self._messages.append(("info", msg))

    async def warning(self, msg):
        self._messages.append(("warning", msg))


# --- Fake adapters ---


class FakeAdapter(BaseAdapter):
    provider_name = "fake"

    def __init__(self, output="test output", status="success", error="", delay=0):
        self._output = output
        self._status = status
        self._error = error
        self._delay = delay

    def _binary_name(self):
        return "fake"

    def check_available(self):
        return True

    def build_command(self, prompt, workdir, **kw):
        return ["echo", prompt]

    def parse_output(self, lines):
        return "\n".join(lines), "", ""

    async def run(self, prompt="", **kw):
        if self._delay:
            await asyncio.sleep(self._delay)
        return AdapterResult(
            provider=self.provider_name,
            status=self._status,
            output=self._output,
            summary=self._output[:100],
            duration_seconds=1.5,
            error=self._error,
        )


class SlowAdapter(FakeAdapter):
    """Adapter that blocks until cancelled."""

    async def run(self, prompt="", **kw):
        try:
            await asyncio.sleep(100)  # effectively forever
        except asyncio.CancelledError:
            raise
        return AdapterResult(
            provider=self.provider_name,
            status="success",
            output="should not reach",
            summary="",
            duration_seconds=0,
        )


class PausableAdapter(FakeAdapter):
    """Adapter with controllable delay for pause/resume testing."""

    async def run(self, prompt="", **kw):
        # Short delay to give time for pause to be issued
        await asyncio.sleep(0.3)
        return AdapterResult(
            provider=self.provider_name,
            status="success",
            output="pausable result",
            summary="pausable result",
            duration_seconds=0.3,
        )


# --- Common patches ---


def _standard_patches(adapter=None):
    """Return context manager stack for standard server patches."""
    if adapter is None:
        adapter = FakeAdapter()

    return (
        patch("vyane.server._ensure_custom_providers_loaded"),
        patch(
            "vyane.server.load_config",
            return_value=MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
            ),
        ),
        patch(
            "vyane.server._detect_and_build_exclusions",
            return_value=(
                MagicMock(provider="", client_name="test", platform="test"),
                [],
            ),
        ),
        patch("vyane.server._get_adapter", return_value=adapter),
        patch("vyane.server.load_policy"),
        patch("vyane.server.check_policy", return_value=MagicMock(allowed=True)),
        patch("vyane.server.count_recent", return_value=0),
        patch("vyane.server.log_dispatch"),
        patch("vyane.server.log_result"),
    )


class TestPartialOutputStreaming:
    """Test that mux_task_status returns accumulated output_preview."""

    @pytest.mark.asyncio
    async def test_status_returns_output_preview_while_running(self):
        """Running tasks should have output_preview and output_lines."""
        from vyane.server import mux_task_status

        status = DispatchStatus(
            run_id="stream1",
            provider="codex",
            task_summary="streaming task",
            status="running",
            started_at=time.time() - 5.0,
            elapsed_seconds=5.0,
            output_preview="partial output so far...",
            output_lines=42,
            async_mode=True,
        )
        with patch("vyane.server.read_status", return_value=status):
            result = await mux_task_status(run_id="stream1")

        data = json.loads(result)
        assert data["status"] == "running"
        assert data["output_preview"] == "partial output so far..."
        assert data["output_lines"] == 42

    @pytest.mark.asyncio
    async def test_async_mode_uses_longer_preview(self):
        """Async dispatch should use 2000 char preview limit."""
        from vyane.server import mux_dispatch

        long_output = "x" * 1500  # longer than 200, shorter than 2000
        ctx = FakeContext()

        class LongOutputAdapter(FakeAdapter):
            async def run(self, prompt="", **kw):
                # Simulate progress callback with long output
                on_progress = kw.get("on_progress")
                if on_progress:
                    on_progress(long_output)
                return AdapterResult(
                    provider=self.provider_name,
                    status="success",
                    output=long_output,
                    summary=long_output[:100],
                    duration_seconds=0.5,
                )

        adapter = LongOutputAdapter()
        patches = _standard_patches(adapter)
        status_writes = []

        def capture_write(status):
            status_writes.append(
                DispatchStatus(
                    run_id=status.run_id,
                    provider=status.provider,
                    status=status.status,
                    output_preview=status.output_preview,
                    output_lines=status.output_lines,
                    async_mode=status.async_mode,
                    result=status.result,
                )
            )

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patch("vyane.server.write_status", side_effect=capture_write),
            patch("vyane.server.remove_status"),
        ):
            result = await mux_dispatch(
                provider="fake",
                task="test long preview",
                ctx=ctx,
                async_mode=True,
            )

            # Wait for background task to complete
            await asyncio.sleep(0.5)

        # Check that preview captures more than 200 chars
        progress_writes = [
            w for w in status_writes if w.output_preview and len(w.output_preview) > 200
        ]
        assert len(progress_writes) > 0, (
            f"Expected at least one write with >200 char preview, "
            f"got previews: {[len(w.output_preview) for w in status_writes]}"
        )

    @pytest.mark.asyncio
    async def test_status_includes_paused_field(self):
        """mux_task_status should return paused field."""
        from vyane.server import mux_task_status

        status = DispatchStatus(
            run_id="p1",
            provider="codex",
            task_summary="paused task",
            status="running",
            started_at=time.time(),
            elapsed_seconds=3.0,
            async_mode=True,
            paused=True,
        )
        with patch("vyane.server.read_status", return_value=status):
            result = await mux_task_status(run_id="p1")

        data = json.loads(result)
        assert data["paused"] is True


class TestPauseResume:
    """Test pause/resume lifecycle for async tasks."""

    @pytest.fixture(autouse=True)
    def _reset_loader(self):
        """Reset custom provider loader flag."""
        from vyane.server import _ensure_custom_providers_loaded

        _ensure_custom_providers_loaded._done = False
        yield
        _ensure_custom_providers_loaded._done = False

    @pytest.mark.asyncio
    async def test_pause_nonexistent_task(self):
        """Pausing a non-existent task returns error."""
        from vyane.server import mux_task_pause

        with patch("vyane.server.read_status", return_value=None):
            result = await mux_task_pause(run_id="nonexistent")

        data = json.loads(result)
        assert data["status"] == "not_found"
        assert "nonexistent" in data["error"]

    @pytest.mark.asyncio
    async def test_resume_nonexistent_task(self):
        """Resuming a non-existent task returns error."""
        from vyane.server import mux_task_resume

        with patch("vyane.server.read_status", return_value=None):
            result = await mux_task_resume(run_id="nonexistent")

        data = json.loads(result)
        assert data["status"] == "not_found"
        assert "nonexistent" in data["error"]

    @pytest.mark.asyncio
    async def test_pause_completed_task(self):
        """Pausing a completed task returns appropriate message."""
        from vyane.server import mux_task_pause

        status = DispatchStatus(
            run_id="done1",
            status="success",
            result={"output": "done"},
        )
        with patch("vyane.server.read_status", return_value=status):
            result = await mux_task_pause(run_id="done1")

        data = json.loads(result)
        assert data["status"] == "success"
        assert "already completed" in data["message"]

    @pytest.mark.asyncio
    async def test_pause_resume_lifecycle(self):
        """Full pause → resume lifecycle on a running async task."""
        import vyane.server as srv
        from vyane.server import mux_dispatch, mux_task_pause, mux_task_resume

        ctx = FakeContext()
        adapter = SlowAdapter()

        patches = _standard_patches(adapter)
        status_writes = {}

        def capture_write(status):
            status_writes[status.run_id] = DispatchStatus(
                run_id=status.run_id,
                provider=status.provider,
                status=status.status,
                async_mode=status.async_mode,
                paused=status.paused,
            )

        def fake_read_status(rid):
            return status_writes.get(rid)

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patch("vyane.server.write_status", side_effect=capture_write),
            patch("vyane.server.remove_status"),
            patch("vyane.server.read_status", side_effect=fake_read_status),
        ):
            result = await mux_dispatch(
                provider="fake",
                task="pause test",
                ctx=ctx,
                async_mode=True,
            )
            data = json.loads(result)
            run_id = data["run_id"]

            # Task should be running
            assert run_id in srv._async_tasks
            assert run_id in srv._pause_events

            # Pause it
            pause_result = await mux_task_pause(run_id=run_id)
            pause_data = json.loads(pause_result)
            assert pause_data["status"] == "paused"

            # Verify pause event is cleared
            assert not srv._pause_events[run_id].is_set()

            # Verify status file was updated with paused=True
            written = status_writes.get(run_id)
            assert written is not None
            assert written.paused is True

            # Resume it
            resume_result = await mux_task_resume(run_id=run_id)
            resume_data = json.loads(resume_result)
            assert resume_data["status"] == "resumed"

            # Verify pause event is set again
            assert srv._pause_events[run_id].is_set()

            # Verify status file was updated with paused=False
            written = status_writes.get(run_id)
            assert written is not None
            assert written.paused is False

            # Clean up: cancel the task
            bg_task = srv._async_tasks.get(run_id)
            if bg_task:
                bg_task.cancel()
                try:
                    await bg_task
                except (asyncio.CancelledError, Exception):
                    pass
            srv._async_tasks.pop(run_id, None)
            srv._pause_events.pop(run_id, None)

    @pytest.mark.asyncio
    async def test_cancelled_background_task_re_raises_cancelled_error(self):
        import vyane.server as srv
        from vyane.server import mux_dispatch

        ctx = FakeContext()
        adapter = SlowAdapter()
        patches = _standard_patches(adapter)

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patch("vyane.server.write_status"),
            patch("vyane.server.remove_status"),
        ):
            result = await mux_dispatch(
                provider="fake",
                task="cancel test",
                ctx=ctx,
                async_mode=True,
            )
            run_id = json.loads(result)["run_id"]
            bg_task = srv._async_tasks[run_id]
            bg_task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await bg_task

        srv._async_tasks.pop(run_id, None)
        srv._pause_events.pop(run_id, None)

    @pytest.mark.asyncio
    async def test_pause_after_dispatch_does_not_block_result_commit(self):
        import vyane.server as srv
        from vyane.server import mux_dispatch

        ctx = FakeContext()
        run_id_holder = {}
        status_writes = {}

        class PauseOnReturnAdapter(FakeAdapter):
            async def run(self, prompt="", **kw):
                while "id" not in run_id_holder:
                    await asyncio.sleep(0)
                run_id = run_id_holder["id"]
                while run_id not in srv._pause_events:
                    await asyncio.sleep(0)
                srv._pause_events[run_id].clear()
                return AdapterResult(
                    provider=self.provider_name,
                    status="success",
                    output="finished",
                    summary="finished",
                    duration_seconds=0.1,
                )

        adapter = PauseOnReturnAdapter()
        patches = _standard_patches(adapter)

        def capture_write(status):
            run_id_holder.setdefault("id", status.run_id)
            status_writes[status.run_id] = DispatchStatus(
                run_id=status.run_id,
                provider=status.provider,
                status=status.status,
                async_mode=status.async_mode,
                paused=status.paused,
                result=status.result,
            )

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patch("vyane.server.write_status", side_effect=capture_write),
            patch("vyane.server.remove_status"),
        ):
            result = await mux_dispatch(
                provider="fake",
                task="pause after dispatch",
                ctx=ctx,
                async_mode=True,
            )
            run_id = json.loads(result)["run_id"]

            for _ in range(50):
                written = status_writes.get(run_id)
                if written and written.result is not None:
                    break
                await asyncio.sleep(0.01)

        written = status_writes.get(run_id)
        assert written is not None
        assert written.status == "success"
        assert written.result is not None
        assert run_id not in srv._async_tasks


class TestTaskList:
    """Test mux_task_list tool."""

    @pytest.mark.asyncio
    async def test_empty_task_list(self):
        """Empty status directory returns empty list."""
        from vyane.server import mux_task_list

        with patch("vyane.server.list_active", return_value=[]):
            result = await mux_task_list()

        data = json.loads(result)
        assert data["total"] == 0
        assert data["tasks"] == []

    @pytest.mark.asyncio
    async def test_task_list_with_multiple_tasks(self):
        """Task list returns all active tasks with metadata."""
        from vyane.server import mux_task_list

        now = time.time()
        statuses = [
            DispatchStatus(
                run_id="task1",
                provider="codex",
                task_summary="first task",
                status="running",
                started_at=now - 10.0,
                elapsed_seconds=10.0,
                async_mode=True,
                paused=False,
            ),
            DispatchStatus(
                run_id="task2",
                provider="gemini",
                task_summary="second task",
                status="running",
                started_at=now - 5.0,
                elapsed_seconds=5.0,
                async_mode=True,
                paused=True,
            ),
        ]

        with patch("vyane.server.list_active", return_value=statuses):
            result = await mux_task_list()

        data = json.loads(result)
        assert data["total"] == 2
        assert len(data["tasks"]) == 2

        # First task (sorted by started_at, earlier first)
        t1 = data["tasks"][0]
        assert t1["run_id"] == "task1"
        assert t1["provider"] == "codex"
        assert t1["status"] == "running"
        assert t1["paused"] is False
        assert t1["task_summary"] == "first task"

        # Second task
        t2 = data["tasks"][1]
        assert t2["run_id"] == "task2"
        assert t2["provider"] == "gemini"
        assert t2["paused"] is True

    @pytest.mark.asyncio
    async def test_task_list_sorted_by_start_time(self):
        """Tasks should be sorted by start time (earliest first)."""
        from vyane.server import mux_task_list

        now = time.time()
        # list_active already returns sorted, verify we preserve order
        statuses = [
            DispatchStatus(
                run_id="old",
                provider="codex",
                status="running",
                started_at=now - 60.0,
                async_mode=True,
            ),
            DispatchStatus(
                run_id="new",
                provider="gemini",
                status="running",
                started_at=now - 1.0,
                async_mode=True,
            ),
        ]

        with patch("vyane.server.list_active", return_value=statuses):
            result = await mux_task_list()

        data = json.loads(result)
        assert data["tasks"][0]["run_id"] == "old"
        assert data["tasks"][1]["run_id"] == "new"


class TestDispatchStatusPaused:
    """Tests for the paused field in DispatchStatus."""

    def test_default_paused_false(self):
        status = DispatchStatus()
        assert status.paused is False

    def test_paused_true(self):
        status = DispatchStatus(run_id="p1", paused=True)
        assert status.paused is True

    def test_paused_roundtrip(self, tmp_path):
        """Paused field survives write/read cycle."""
        with patch("vyane.status._status_dir", return_value=tmp_path):
            status = DispatchStatus(
                run_id="prt",
                provider="codex",
                status="running",
                paused=True,
                async_mode=True,
                started_at=time.time(),
            )
            write_status(status)
            result = read_status("prt")

        assert result is not None
        assert result.paused is True
