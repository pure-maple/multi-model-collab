"""Unit tests for failover and progress notification logic.

Run with: cd mcp/modelmux && uv run python tests/test_failover.py
"""

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "src")

from vyane.adapters.base import AdapterResult
from vyane.server import _get_fallback_candidates, mux_dispatch


def make_mock_ctx(client_name: str = "test-runner"):
    ctx = MagicMock()
    ctx._request_context = MagicMock()
    ctx.session.client_params.clientInfo.name = client_name
    ctx.session.client_params.clientInfo.version = "1.0"
    ctx.warning = AsyncMock()
    ctx.info = AsyncMock()
    return ctx


def test_fallback_candidates_basic():
    """Candidates should exclude current and excluded providers."""
    candidates = _get_fallback_candidates("codex", [])
    assert candidates == ["gemini", "claude", "ollama"]
    print("[PASS] fallback candidates basic")


def test_fallback_candidates_with_exclusions():
    candidates = _get_fallback_candidates("codex", ["claude"])
    assert candidates == ["gemini", "ollama"]
    print("[PASS] fallback candidates with exclusions")


def test_fallback_candidates_all_excluded():
    candidates = _get_fallback_candidates("codex", ["gemini", "claude", "ollama"])
    assert candidates == []
    print("[PASS] fallback candidates all excluded")


def test_failover_on_execution_error():
    """When primary provider errors, should failover to next available."""
    ctx = make_mock_ctx()

    error_result = AdapterResult(
        run_id="abc",
        provider="codex",
        status="error",
        error="CLI crashed",
    )
    success_result = AdapterResult(
        run_id="def",
        provider="gemini",
        status="success",
        output="Hello!",
        session_id="s1",
        duration_seconds=2.0,
    )

    call_count = {"codex": 0, "gemini": 0}

    async def mock_run(self, **kwargs):
        call_count[self.provider_name] += 1
        if self.provider_name == "codex":
            return error_result
        return success_result

    with (
        patch(
            "vyane.adapters.codex.CodexAdapter.check_available", return_value=True
        ),
        patch(
            "vyane.adapters.gemini.GeminiAdapter.check_available", return_value=True
        ),
        patch(
            "vyane.adapters.claude.ClaudeAdapter.check_available", return_value=False
        ),
        patch("vyane.adapters.base.BaseAdapter.run", mock_run),
    ):
        raw = asyncio.run(
            mux_dispatch(
                provider="codex",
                task="test task",
                ctx=ctx,
                workdir="/tmp",
                failover=True,
            )
        )
        result = json.loads(raw)
        assert result["provider"] == "gemini", (
            f"Expected gemini, got {result['provider']}"
        )
        assert result["status"] == "success"
        assert result["failover_from"] == "codex"
        assert call_count["codex"] == 1
        assert call_count["gemini"] == 1
    print("[PASS] failover on execution error")


def test_no_failover_when_disabled():
    """When failover=False, should return error without retrying."""
    ctx = make_mock_ctx()

    error_result = AdapterResult(
        run_id="abc",
        provider="codex",
        status="error",
        error="CLI crashed",
    )

    async def mock_run(self, **kwargs):
        return error_result

    with (
        patch(
            "vyane.adapters.codex.CodexAdapter.check_available", return_value=True
        ),
        patch("vyane.adapters.base.BaseAdapter.run", mock_run),
    ):
        raw = asyncio.run(
            mux_dispatch(
                provider="codex",
                task="test task",
                ctx=ctx,
                workdir="/tmp",
                failover=False,
            )
        )
        result = json.loads(raw)
        assert result["status"] == "error"
        assert "failover_from" not in result
    print("[PASS] no failover when disabled")


def test_no_failover_with_session_id():
    """Sessions are provider-specific, so no failover."""
    ctx = make_mock_ctx()

    error_result = AdapterResult(
        run_id="abc",
        provider="codex",
        status="error",
        error="session not found",
    )

    async def mock_run(self, **kwargs):
        return error_result

    with (
        patch(
            "vyane.adapters.codex.CodexAdapter.check_available", return_value=True
        ),
        patch("vyane.adapters.base.BaseAdapter.run", mock_run),
    ):
        raw = asyncio.run(
            mux_dispatch(
                provider="codex",
                task="continue the discussion",
                ctx=ctx,
                workdir="/tmp",
                session_id="existing-session-123",
                failover=True,
            )
        )
        result = json.loads(raw)
        assert result["status"] == "error"
        assert "failover_from" not in result
    print("[PASS] no failover with session_id")


def test_retry_same_provider_on_error():
    """max_retries > 1 should retry the same provider before failover."""
    ctx = make_mock_ctx()

    call_count = [0]

    async def mock_run(self, **kwargs):
        call_count[0] += 1
        if call_count[0] < 3:
            return AdapterResult(
                run_id="abc",
                provider="codex",
                status="error",
                error="transient failure",
            )
        return AdapterResult(
            run_id="abc",
            provider="codex",
            status="success",
            output="worked on attempt 3",
            duration_seconds=1.0,
        )

    with (
        patch(
            "vyane.adapters.codex.CodexAdapter.check_available",
            return_value=True,
        ),
        patch("vyane.adapters.base.BaseAdapter.run", mock_run),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        raw = asyncio.run(
            mux_dispatch(
                provider="codex",
                task="test retry",
                ctx=ctx,
                workdir="/tmp",
                max_retries=3,
                failover=False,
            )
        )
        result = json.loads(raw)
        assert result["status"] == "success"
        assert call_count[0] == 3
    print("[PASS] retry same provider on error")


def test_retry_no_retry_when_max_retries_1():
    """max_retries=1 (default) should not retry."""
    ctx = make_mock_ctx()

    call_count = [0]

    async def mock_run(self, **kwargs):
        call_count[0] += 1
        return AdapterResult(
            run_id="abc",
            provider="codex",
            status="timeout",
            error="Timed out",
        )

    with (
        patch(
            "vyane.adapters.codex.CodexAdapter.check_available",
            return_value=True,
        ),
        patch("vyane.adapters.base.BaseAdapter.run", mock_run),
    ):
        raw = asyncio.run(
            mux_dispatch(
                provider="codex",
                task="test no retry",
                ctx=ctx,
                workdir="/tmp",
                max_retries=1,
                failover=False,
            )
        )
        result = json.loads(raw)
        assert result["status"] == "timeout"
        assert call_count[0] == 1
    print("[PASS] no retry when max_retries=1")


def test_retry_then_failover():
    """After retries exhaust, should still failover to other providers."""
    ctx = make_mock_ctx()

    async def mock_run(self, **kwargs):
        if self.provider_name == "codex":
            return AdapterResult(
                run_id="abc",
                provider="codex",
                status="error",
                error="always fails",
            )
        return AdapterResult(
            run_id="def",
            provider="gemini",
            status="success",
            output="gemini saved us",
            duration_seconds=1.0,
        )

    with (
        patch(
            "vyane.adapters.codex.CodexAdapter.check_available",
            return_value=True,
        ),
        patch(
            "vyane.adapters.gemini.GeminiAdapter.check_available",
            return_value=True,
        ),
        patch(
            "vyane.adapters.claude.ClaudeAdapter.check_available",
            return_value=False,
        ),
        patch("vyane.adapters.base.BaseAdapter.run", mock_run),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        raw = asyncio.run(
            mux_dispatch(
                provider="codex",
                task="retry then failover",
                ctx=ctx,
                workdir="/tmp",
                max_retries=2,
                failover=True,
            )
        )
        result = json.loads(raw)
        assert result["status"] == "success"
        assert result["provider"] == "gemini"
        assert result["failover_from"] == "codex"
    print("[PASS] retry then failover")


def test_retry_clamped_to_5():
    """max_retries > 5 should be clamped to 5."""
    ctx = make_mock_ctx()

    call_count = [0]

    async def mock_run(self, **kwargs):
        call_count[0] += 1
        return AdapterResult(
            run_id="abc",
            provider="codex",
            status="error",
            error="keeps failing",
        )

    with (
        patch(
            "vyane.adapters.codex.CodexAdapter.check_available",
            return_value=True,
        ),
        patch("vyane.adapters.base.BaseAdapter.run", mock_run),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        raw = asyncio.run(
            mux_dispatch(
                provider="codex",
                task="test clamp",
                ctx=ctx,
                workdir="/tmp",
                max_retries=10,
                failover=False,
            )
        )
        result = json.loads(raw)
        assert result["status"] == "error"
        # 1 initial + 4 retries = 5 total (clamped from 10)
        assert call_count[0] == 5
    print("[PASS] retry clamped to 5")


def test_progress_notification_sent():
    """ctx.info() should be called with dispatch progress."""
    ctx = make_mock_ctx()

    success_result = AdapterResult(
        run_id="abc",
        provider="codex",
        status="success",
        output="done",
        session_id="s1",
        duration_seconds=1.0,
    )

    async def mock_run(self, **kwargs):
        return success_result

    with (
        patch(
            "vyane.adapters.codex.CodexAdapter.check_available", return_value=True
        ),
        patch("vyane.adapters.base.BaseAdapter.run", mock_run),
    ):
        asyncio.run(
            mux_dispatch(
                provider="codex",
                task="hello",
                ctx=ctx,
                workdir="/tmp",
            )
        )
        # Should have been called with dispatch progress
        info_calls = [str(c) for c in ctx.info.call_args_list]
        assert any("codex" in c.lower() for c in info_calls), (
            f"Expected progress info about codex, got: {info_calls}"
        )
    print("[PASS] progress notification sent")


def main():
    tests = [
        test_fallback_candidates_basic,
        test_fallback_candidates_with_exclusions,
        test_fallback_candidates_all_excluded,
        test_failover_on_execution_error,
        test_no_failover_when_disabled,
        test_no_failover_with_session_id,
        test_retry_same_provider_on_error,
        test_retry_no_retry_when_max_retries_1,
        test_retry_then_failover,
        test_retry_clamped_to_5,
        test_progress_notification_sent,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Failover tests: {passed}/{passed + failed} passed")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
