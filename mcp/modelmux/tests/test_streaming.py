"""Tests for streaming output / on_progress callback support."""

import time

from vyane.adapters.base import AdapterResult, BaseAdapter
from vyane.status import DispatchStatus


class FakeStreamingAdapter(BaseAdapter):
    """Adapter that simulates streaming output for testing."""

    provider_name = "fake"

    def _binary_name(self) -> str:
        return "echo"

    def check_available(self) -> bool:
        return True

    def build_command(self, prompt, workdir, sandbox="read-only",
                      session_id="", extra_args=None):
        return ["echo", "test"]

    def parse_output(self, lines):
        return "\n".join(lines), "", ""


def test_dispatch_status_has_output_lines():
    """DispatchStatus should have output_lines field."""
    status = DispatchStatus(
        run_id="test",
        provider="codex",
        output_lines=42,
    )
    assert status.output_lines == 42


def test_dispatch_status_default_output_lines():
    """output_lines defaults to 0."""
    status = DispatchStatus()
    assert status.output_lines == 0


def test_on_progress_called_per_line():
    """on_progress should be called for each output line."""
    import asyncio

    adapter = FakeStreamingAdapter()
    progress_calls = []

    def on_progress(msg: str) -> None:
        progress_calls.append(msg)

    result = asyncio.run(
        adapter.run(
            prompt="hello",
            workdir="/tmp",
            on_progress=on_progress,
        )
    )

    # Should have at least the initial "Running fake CLI..." message
    assert len(progress_calls) >= 1
    assert "Running fake CLI..." in progress_calls[0]


def test_throttled_progress_callback():
    """Verify throttle logic: only write status when interval has passed."""
    last_write = [0.0]
    write_count = [0]
    interval = 0.5

    def throttled_callback(msg: str) -> None:
        now = time.time()
        if now - last_write[0] >= interval:
            last_write[0] = now
            write_count[0] += 1

    # Simulate rapid-fire calls (should be throttled)
    start = time.time()
    for i in range(100):
        throttled_callback(f"line {i}")

    # All calls happen in <0.01s, so only 1 write should occur
    assert write_count[0] == 1


def test_adapter_result_schema():
    """AdapterResult should serialize correctly."""
    result = AdapterResult(
        run_id="abc",
        provider="codex",
        status="success",
        summary="test output",
        output="full output here",
        session_id="sess-1",
        duration_seconds=1.234,
    )
    d = result.to_dict()
    assert d["run_id"] == "abc"
    assert d["duration_seconds"] == 1.2
    assert "error" not in d
