"""Tests for async dispatch mode (MER-85).

Covers async_mode parameter in mux_dispatch, mux_task_status, and
mux_task_cancel tools.
"""

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from modelmux.adapters.base import AdapterResult, BaseAdapter
from modelmux.status import DispatchStatus, read_status, write_status


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


# --- Fake adapter for testing ---


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


# --- Common patches ---

def _standard_patches(adapter=None):
    """Return context manager stack for standard server patches."""
    if adapter is None:
        adapter = FakeAdapter()

    return (
        patch("modelmux.server._ensure_custom_providers_loaded"),
        patch("modelmux.server.load_config", return_value=MagicMock(
            active_profile="default",
            profiles={},
            disabled_providers=[],
            routing_rules=[],
            default_provider="codex",
            auto_exclude_caller=True,
        )),
        patch("modelmux.server._detect_and_build_exclusions", return_value=(
            MagicMock(provider="", client_name="test", platform="test"),
            [],
        )),
        patch("modelmux.server._get_adapter", return_value=adapter),
        patch("modelmux.server.load_policy"),
        patch("modelmux.server.check_policy", return_value=MagicMock(allowed=True)),
        patch("modelmux.server.count_recent", return_value=0),
        patch("modelmux.server.log_dispatch"),
        patch("modelmux.server.log_result"),
    )


class TestAsyncModeDispatch:
    @pytest.fixture(autouse=True)
    def _reset_loader(self):
        """Reset custom provider loader flag."""
        from modelmux.server import _ensure_custom_providers_loaded
        _ensure_custom_providers_loaded._done = False
        yield
        _ensure_custom_providers_loaded._done = False

    @pytest.mark.asyncio
    async def test_async_mode_returns_immediately(self, tmp_path):
        """async_mode=True should return accepted status with run_id."""
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        adapter = FakeAdapter(output="hello", delay=0.5)

        patches = _standard_patches(adapter)
        with (
            patches[0], patches[1], patches[2], patches[3],
            patches[4], patches[5], patches[6], patches[7], patches[8],
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
        ):
            result = await mux_dispatch(
                provider="fake",
                task="test async",
                ctx=ctx,
                async_mode=True,
            )

        data = json.loads(result)
        assert data["status"] == "accepted"
        assert "run_id" in data
        assert data["async_mode"] is True
        assert data["provider"] == "fake"

        # Allow background task to complete
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_sync_mode_unchanged(self, tmp_path):
        """async_mode=False (default) returns full result."""
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        adapter = FakeAdapter(output="sync result")

        patches = _standard_patches(adapter)
        with (
            patches[0], patches[1], patches[2], patches[3],
            patches[4], patches[5], patches[6], patches[7], patches[8],
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
        ):
            result = await mux_dispatch(
                provider="fake",
                task="test sync",
                ctx=ctx,
                async_mode=False,
            )

        data = json.loads(result)
        assert data["status"] == "success"
        assert data["output"] == "sync result"
        # Should NOT have async_mode key
        assert "async_mode" not in data

    @pytest.mark.asyncio
    async def test_async_task_stores_result(self, tmp_path):
        """Background task should write result to status file."""
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        adapter = FakeAdapter(output="bg result")

        patches = _standard_patches(adapter)
        status_writes = []

        def capture_write(status):
            status_writes.append(DispatchStatus(
                run_id=status.run_id,
                provider=status.provider,
                status=status.status,
                async_mode=status.async_mode,
                result=status.result,
            ))

        with (
            patches[0], patches[1], patches[2], patches[3],
            patches[4], patches[5], patches[6], patches[7], patches[8],
            patch("modelmux.server.write_status", side_effect=capture_write),
            patch("modelmux.server.remove_status"),
        ):
            result = await mux_dispatch(
                provider="fake",
                task="test bg",
                ctx=ctx,
                async_mode=True,
            )

            data = json.loads(result)
            assert data["status"] == "accepted"

            # Wait for background task to finish
            await asyncio.sleep(0.3)

        # The last write should contain the result
        final_writes = [w for w in status_writes if w.result is not None]
        assert len(final_writes) >= 1
        assert final_writes[-1].result["output"] == "bg result"


class TestMuxTaskStatus:
    @pytest.mark.asyncio
    async def test_status_not_found(self):
        from modelmux.server import mux_task_status

        with patch("modelmux.server.read_status", return_value=None):
            result = await mux_task_status(run_id="nonexistent")

        data = json.loads(result)
        assert data["status"] == "not_found"
        assert "nonexistent" in data["error"]

    @pytest.mark.asyncio
    async def test_status_running(self):
        from modelmux.server import mux_task_status

        status = DispatchStatus(
            run_id="abc123",
            provider="codex",
            task_summary="test task",
            status="running",
            started_at=time.time(),
            elapsed_seconds=5.2,
            output_preview="processing...",
            output_lines=10,
            async_mode=True,
        )
        with patch("modelmux.server.read_status", return_value=status):
            result = await mux_task_status(run_id="abc123")

        data = json.loads(result)
        assert data["status"] == "running"
        assert data["output_preview"] == "processing..."
        assert data["output_lines"] == 10

    @pytest.mark.asyncio
    async def test_status_completed_without_output(self):
        from modelmux.server import mux_task_status

        status = DispatchStatus(
            run_id="abc123",
            provider="codex",
            task_summary="test task",
            status="success",
            elapsed_seconds=10.0,
            async_mode=True,
            result={
                "status": "success",
                "provider": "codex",
                "output": "full output here",
                "duration_seconds": 9.5,
            },
        )
        with patch("modelmux.server.read_status", return_value=status):
            result = await mux_task_status(run_id="abc123", include_output=False)

        data = json.loads(result)
        assert data["status"] == "success"
        assert data["result_status"] == "success"
        assert "result" not in data  # full result not included

    @pytest.mark.asyncio
    async def test_status_completed_with_output(self):
        from modelmux.server import mux_task_status

        status = DispatchStatus(
            run_id="abc123",
            provider="codex",
            task_summary="test task",
            status="success",
            elapsed_seconds=10.0,
            async_mode=True,
            result={
                "status": "success",
                "provider": "codex",
                "output": "full output here",
                "duration_seconds": 9.5,
            },
        )
        with patch("modelmux.server.read_status", return_value=status):
            result = await mux_task_status(run_id="abc123", include_output=True)

        data = json.loads(result)
        assert data["status"] == "success"
        assert data["result"]["output"] == "full output here"


class TestMuxTaskCancel:
    @pytest.mark.asyncio
    async def test_cancel_not_found(self):
        from modelmux.server import mux_task_cancel

        with patch("modelmux.server.read_status", return_value=None):
            result = await mux_task_cancel(run_id="nonexistent")

        data = json.loads(result)
        assert data["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_cancel_already_completed(self):
        from modelmux.server import mux_task_cancel

        status = DispatchStatus(
            run_id="done1",
            status="success",
            result={"output": "done"},
        )
        with patch("modelmux.server.read_status", return_value=status):
            result = await mux_task_cancel(run_id="done1")

        data = json.loads(result)
        assert data["status"] == "success"
        assert "already completed" in data["message"]

    @pytest.mark.asyncio
    async def test_cancel_running_task(self, tmp_path):
        """Cancel a running async task via _async_tasks dict."""
        import modelmux.server as srv
        from modelmux.server import mux_dispatch, mux_task_cancel

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
            )

        def fake_read_status(rid):
            s = status_writes.get(rid)
            return s

        with (
            patches[0], patches[1], patches[2], patches[3],
            patches[4], patches[5], patches[6], patches[7], patches[8],
            patch("modelmux.server.write_status", side_effect=capture_write),
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.read_status", side_effect=fake_read_status),
        ):
            result = await mux_dispatch(
                provider="fake",
                task="long running",
                ctx=ctx,
                async_mode=True,
            )
            data = json.loads(result)
            run_id = data["run_id"]

            # Task should be in _async_tasks
            assert run_id in srv._async_tasks

            # Cancel it
            cancel_result = await mux_task_cancel(run_id=run_id)

            cancel_data = json.loads(cancel_result)
            assert cancel_data["status"] == "cancelled"

            # Task should be removed from _async_tasks after cancel
            assert run_id not in srv._async_tasks


class TestDispatchStatusExtended:
    """Tests for the new fields in DispatchStatus."""

    def test_default_new_fields(self):
        status = DispatchStatus()
        assert status.async_mode is False
        assert status.result is None

    def test_with_async_mode(self):
        status = DispatchStatus(
            run_id="a1",
            provider="codex",
            async_mode=True,
        )
        assert status.async_mode is True

    def test_with_result(self):
        result_dict = {"status": "success", "output": "hello"}
        status = DispatchStatus(
            run_id="a2",
            provider="gemini",
            result=result_dict,
        )
        assert status.result == result_dict


class TestReadStatus:
    def test_read_existing(self, tmp_path):
        with patch("modelmux.status._status_dir", return_value=tmp_path):
            status = DispatchStatus(
                run_id="rd1",
                provider="codex",
                status="running",
                async_mode=True,
                started_at=time.time(),
            )
            write_status(status)
            result = read_status("rd1")

        assert result is not None
        assert result.run_id == "rd1"
        assert result.async_mode is True

    def test_read_nonexistent(self, tmp_path):
        with patch("modelmux.status._status_dir", return_value=tmp_path):
            result = read_status("doesnotexist")
        assert result is None

    def test_read_with_result(self, tmp_path):
        with patch("modelmux.status._status_dir", return_value=tmp_path):
            status = DispatchStatus(
                run_id="rd2",
                provider="codex",
                status="success",
                async_mode=True,
                result={"output": "hello", "status": "success"},
            )
            write_status(status)
            result = read_status("rd2")

        assert result is not None
        assert result.result == {"output": "hello", "status": "success"}
