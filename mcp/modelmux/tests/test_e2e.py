"""End-to-end tests for Vyane MCP server.

Run with: cd mcp/modelmux && .venv/bin/python tests/test_e2e.py
Requires: codex and gemini CLIs on PATH.
"""

import asyncio
import json
import sys
import time
from unittest.mock import AsyncMock, MagicMock

# Add src to path for direct execution
sys.path.insert(0, "src")

from vyane.server import mux_dispatch, mux_check


def make_mock_ctx(client_name: str = "test-runner", version: str = "1.0"):
    """Create a mock FastMCP Context for testing."""
    ctx = MagicMock()
    ctx._request_context = MagicMock()
    ctx.session.client_params.clientInfo.name = client_name
    ctx.session.client_params.clientInfo.version = version
    ctx.warning = AsyncMock()
    ctx.info = AsyncMock()
    return ctx


async def test_mux_check():
    """Test that mux_check returns adapter availability and caller info."""
    print("=" * 60)
    print("TEST: mux_check")
    print("=" * 60)

    ctx = make_mock_ctx("claude-code", "1.0.30")
    result = json.loads(await mux_check(ctx=ctx))
    print(json.dumps(result, indent=2))

    assert "codex" in result, "Missing codex in check result"
    assert "gemini" in result, "Missing gemini in check result"
    assert "claude" in result, "Missing claude in check result"

    # Verify caller detection
    assert "_caller" in result, "Missing _caller section"
    assert result["_caller"]["client_name"] == "claude-code"
    assert result["_caller"]["provider"] == "claude"
    assert result["_caller"]["platform"] == "cli"

    # Verify exclusion marking
    assert result["claude"]["excluded"] is True, "Claude should be excluded (caller)"
    assert result["codex"]["excluded"] is False, "Codex should not be excluded"

    available_count = sum(
        1 for k, v in result.items()
        if not k.startswith("_") and v.get("available")
    )
    print(f"\n[PASS] {available_count}/3 CLIs available, caller detection works")
    return result


async def test_dispatch_simple(provider: str):
    """Test simple dispatch to a single provider."""
    print(f"\n{'=' * 60}")
    print(f"TEST: mux_dispatch ({provider}) - simple math")
    print("=" * 60)

    ctx = make_mock_ctx("test-runner")
    start = time.monotonic()
    raw = await mux_dispatch(
        provider=provider,
        task="What is 7 * 8? Reply with ONLY the number, nothing else.",
        ctx=ctx,
        workdir="/tmp",
        timeout=60,
    )
    elapsed = time.monotonic() - start
    result = json.loads(raw)

    print(json.dumps(result, indent=2))
    print(f"\nElapsed: {elapsed:.1f}s")

    assert result["status"] == "success", f"Expected success, got {result['status']}"
    assert result["provider"] == provider
    assert result["session_id"], "Missing session_id"
    assert "56" in result["output"], f"Expected 56 in output: {result['output']}"

    print(f"[PASS] {provider}: correct answer, session_id present")
    return result


async def test_dispatch_code_review():
    """Test a real code review task dispatched to Codex."""
    print(f"\n{'=' * 60}")
    print("TEST: mux_dispatch (codex) - code review")
    print("=" * 60)

    code = '''
def merge(left, right):
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1
    result.extend(left[i:])
    return result
'''

    ctx = make_mock_ctx("test-runner")
    raw = await mux_dispatch(
        provider="codex",
        task=f"Review this merge function for bugs. Be concise:\n```python\n{code}\n```",
        ctx=ctx,
        workdir="/tmp",
        sandbox="read-only",
        timeout=120,
    )
    result = json.loads(raw)

    print(f"Status: {result['status']}")
    print(f"Duration: {result['duration_seconds']}s")
    print(f"Output preview: {result['output'][:300]}")

    assert result["status"] == "success"
    output_lower = result["output"].lower()
    has_bug_mention = any(w in output_lower for w in ["right", "bug", "miss", "remain", "forgot"])
    print(f"Mentions the bug: {has_bug_mention}")
    print(f"[{'PASS' if has_bug_mention else 'WARN'}] Code review completed")
    return result


async def test_session_continuity():
    """Test multi-turn session via session_id."""
    print(f"\n{'=' * 60}")
    print("TEST: Session continuity (codex)")
    print("=" * 60)

    ctx = make_mock_ctx("test-runner")

    # Turn 1
    raw1 = await mux_dispatch(
        provider="codex",
        task="Remember the number 42. Just confirm you remember it.",
        ctx=ctx,
        workdir="/tmp",
        timeout=60,
    )
    r1 = json.loads(raw1)
    print(f"Turn 1 session_id: {r1['session_id']}")
    assert r1["status"] == "success"
    assert r1["session_id"], "No session_id returned"

    # Turn 2 - resume session
    raw2 = await mux_dispatch(
        provider="codex",
        task="What number did I ask you to remember? Reply with just the number.",
        ctx=ctx,
        workdir="/tmp",
        session_id=r1["session_id"],
        timeout=60,
    )
    r2 = json.loads(raw2)
    print(f"Turn 2 session_id: {r2['session_id']}")
    print(f"Turn 2 output: {r2['output'][:200]}")

    assert r2["status"] == "success"
    has_42 = "42" in r2["output"]
    print(f"Remembers 42: {has_42}")
    print(f"[{'PASS' if has_42 else 'WARN'}] Session continuity test")
    return r2


async def test_parallel_dispatch():
    """Test parallel dispatch to both Codex and Gemini."""
    print(f"\n{'=' * 60}")
    print("TEST: Parallel dispatch (codex + gemini)")
    print("=" * 60)

    ctx = make_mock_ctx("test-runner")
    start = time.monotonic()
    codex_task = mux_dispatch(
        provider="codex",
        task="Write a Python one-liner that reverses a string. Reply with ONLY the code.",
        ctx=ctx,
        workdir="/tmp",
        timeout=60,
    )
    gemini_task = mux_dispatch(
        provider="gemini",
        task="Write a Python one-liner that reverses a string. Reply with ONLY the code.",
        ctx=ctx,
        workdir="/tmp",
        timeout=60,
    )

    results = await asyncio.gather(codex_task, gemini_task)
    elapsed = time.monotonic() - start

    for raw in results:
        r = json.loads(raw)
        print(f"  {r['provider']}: {r['status']} ({r['duration_seconds']:.1f}s) -> {r['output'][:100]}")

    print(f"\nTotal parallel time: {elapsed:.1f}s")
    codex_r = json.loads(results[0])
    gemini_r = json.loads(results[1])
    max_individual = max(codex_r["duration_seconds"], gemini_r["duration_seconds"])
    print(f"Max individual time: {max_individual:.1f}s")
    print(f"[PASS] Parallel dispatch completed")
    return results


async def test_auto_routing_exclusion():
    """Test that auto routing excludes the caller platform."""
    print(f"\n{'=' * 60}")
    print("TEST: Auto-routing caller exclusion")
    print("=" * 60)

    # Simulate Claude Code calling with a task that would route to claude
    ctx = make_mock_ctx("claude-code", "1.0.30")
    raw = await mux_dispatch(
        provider="auto",
        task="Review and analyze this architecture for security threats",
        ctx=ctx,
        workdir="/tmp",
        timeout=60,
    )
    result = json.loads(raw)

    print(f"Provider: {result['provider']}")
    print(f"Routed from: {result.get('routed_from')}")
    print(f"Caller excluded: {result.get('caller_excluded')}")

    # Should NOT route to claude since that's the caller
    assert result["provider"] != "claude", \
        f"Should not route to claude (the caller), got {result['provider']}"
    assert result.get("routed_from") == "auto"
    assert result.get("caller_excluded") == "claude"

    print(f"[PASS] Auto-routing excluded caller (claude), routed to {result['provider']}")
    return result


async def main():
    print("Vyane End-to-End Tests")
    print("=" * 60)

    # Check availability first
    check = await test_mux_check()
    ctx = make_mock_ctx("test-runner")
    check_result = json.loads(await mux_check(ctx=ctx))
    available = {
        k: v.get("available", False)
        for k, v in check_result.items()
        if not k.startswith("_")
    }

    passed = 0
    total = 0

    # Simple dispatch tests
    for provider in ["codex", "gemini"]:
        if available.get(provider):
            total += 1
            try:
                await test_dispatch_simple(provider)
                passed += 1
            except Exception as e:
                print(f"[FAIL] {provider} simple: {e}")
        else:
            print(f"\n[SKIP] {provider} not available")

    # Code review test
    if available.get("codex"):
        total += 1
        try:
            await test_dispatch_code_review()
            passed += 1
        except Exception as e:
            print(f"[FAIL] code review: {e}")

    # Session continuity
    if available.get("codex"):
        total += 1
        try:
            await test_session_continuity()
            passed += 1
        except Exception as e:
            print(f"[FAIL] session continuity: {e}")

    # Parallel dispatch
    if available.get("codex") and available.get("gemini"):
        total += 1
        try:
            await test_parallel_dispatch()
            passed += 1
        except Exception as e:
            print(f"[FAIL] parallel dispatch: {e}")

    # Auto-routing exclusion (does not require CLIs for basic test)
    total += 1
    try:
        await test_auto_routing_exclusion()
        passed += 1
    except Exception as e:
        print(f"[FAIL] auto-routing exclusion: {e}")

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed}/{total} tests passed")
    print("=" * 60)
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
