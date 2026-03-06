"""Unit tests for failover and progress notification logic.

Run with: cd mcp/modelmux && uv run python tests/test_failover.py
"""

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "src")

from modelmux.adapters.base import AdapterResult
from modelmux.server import _get_fallback_candidates, mux_dispatch


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
    assert candidates == ["gemini", "claude"]
    print("[PASS] fallback candidates basic")


def test_fallback_candidates_with_exclusions():
    candidates = _get_fallback_candidates("codex", ["claude"])
    assert candidates == ["gemini"]
    print("[PASS] fallback candidates with exclusions")


def test_fallback_candidates_all_excluded():
    candidates = _get_fallback_candidates("codex", ["gemini", "claude"])
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
        patch("modelmux.adapters.codex.CodexAdapter.check_available", return_value=True),
        patch("modelmux.adapters.gemini.GeminiAdapter.check_available", return_value=True),
        patch("modelmux.adapters.claude.ClaudeAdapter.check_available", return_value=False),
        patch("modelmux.adapters.base.BaseAdapter.run", mock_run),
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
        assert result["provider"] == "gemini", f"Expected gemini, got {result['provider']}"
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
        patch("modelmux.adapters.codex.CodexAdapter.check_available", return_value=True),
        patch("modelmux.adapters.base.BaseAdapter.run", mock_run),
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
        patch("modelmux.adapters.codex.CodexAdapter.check_available", return_value=True),
        patch("modelmux.adapters.base.BaseAdapter.run", mock_run),
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
        patch("modelmux.adapters.codex.CodexAdapter.check_available", return_value=True),
        patch("modelmux.adapters.base.BaseAdapter.run", mock_run),
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
        assert any("codex" in c.lower() for c in info_calls), \
            f"Expected progress info about codex, got: {info_calls}"
    print("[PASS] progress notification sent")


def main():
    tests = [
        test_fallback_candidates_basic,
        test_fallback_candidates_with_exclusions,
        test_fallback_candidates_all_excluded,
        test_failover_on_execution_error,
        test_no_failover_when_disabled,
        test_no_failover_with_session_id,
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
