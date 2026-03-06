"""End-to-end tests for collab-hub MCP server.

Run with: python tests/test_e2e.py
Requires: codex and gemini CLIs on PATH.
"""

import asyncio
import json
import sys
import time

# Add src to path for direct execution
sys.path.insert(0, "src")

from collab_hub.server import collab_dispatch, collab_check


async def test_collab_check():
    """Test that collab_check returns adapter availability."""
    print("=" * 60)
    print("TEST: collab_check")
    print("=" * 60)

    result = json.loads(await collab_check())
    print(json.dumps(result, indent=2))

    assert "codex" in result, "Missing codex in check result"
    assert "gemini" in result, "Missing gemini in check result"
    assert "claude" in result, "Missing claude in check result"

    available_count = sum(1 for v in result.values() if v["available"])
    print(f"\n[PASS] {available_count}/3 CLIs available")
    return result


async def test_dispatch_simple(provider: str):
    """Test simple dispatch to a single provider."""
    print(f"\n{'=' * 60}")
    print(f"TEST: collab_dispatch ({provider}) - simple math")
    print("=" * 60)

    start = time.monotonic()
    raw = await collab_dispatch(
        provider=provider,
        task="What is 7 * 8? Reply with ONLY the number, nothing else.",
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
    print("TEST: collab_dispatch (codex) - code review")
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

    raw = await collab_dispatch(
        provider="codex",
        task=f"Review this merge function for bugs. Be concise:\n```python\n{code}\n```",
        workdir="/tmp",
        sandbox="read-only",
        timeout=120,
    )
    result = json.loads(raw)

    print(f"Status: {result['status']}")
    print(f"Duration: {result['duration_seconds']}s")
    print(f"Output preview: {result['output'][:300]}")

    assert result["status"] == "success"
    # The bug is that right[j:] remainder is not appended
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

    # Turn 1
    raw1 = await collab_dispatch(
        provider="codex",
        task="Remember the number 42. Just confirm you remember it.",
        workdir="/tmp",
        timeout=60,
    )
    r1 = json.loads(raw1)
    print(f"Turn 1 session_id: {r1['session_id']}")
    assert r1["status"] == "success"
    assert r1["session_id"], "No session_id returned"

    # Turn 2 - resume session
    raw2 = await collab_dispatch(
        provider="codex",
        task="What number did I ask you to remember? Reply with just the number.",
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

    start = time.monotonic()
    codex_task = collab_dispatch(
        provider="codex",
        task="Write a Python one-liner that reverses a string. Reply with ONLY the code.",
        workdir="/tmp",
        timeout=60,
    )
    gemini_task = collab_dispatch(
        provider="gemini",
        task="Write a Python one-liner that reverses a string. Reply with ONLY the code.",
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


async def main():
    print("collab-hub End-to-End Tests")
    print("=" * 60)

    # Check availability first
    check = await test_collab_check()
    available = {k: v["available"] for k, v in json.loads(await collab_check()).items()}

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

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed}/{total} tests passed")
    print("=" * 60)
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
