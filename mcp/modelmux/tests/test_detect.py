"""Unit tests for caller platform detection.

Run with: cd mcp/modelmux && .venv/bin/python tests/test_detect.py
"""

import sys
from unittest.mock import MagicMock

sys.path.insert(0, "src")

from vyane.detect import (
    CallerInfo,
    detect_caller,
    detect_caller_from_env,
    detect_caller_from_session,
    get_excluded_providers,
)


def make_mock_session(name: str, version: str = "1.0"):
    """Create a mock MCP session with clientInfo."""
    session = MagicMock()
    session.client_params.clientInfo.name = name
    session.client_params.clientInfo.version = version
    return session


def test_detect_claude_code():
    session = make_mock_session("claude-code", "1.0.30")
    info = detect_caller_from_session(session)
    assert info.provider == "claude", f"Expected claude, got {info.provider}"
    assert info.platform == "cli"
    assert info.client_name == "claude-code"
    assert info.detection_method == "mcp_client_info"
    print("[PASS] detect Claude Code")


def test_detect_codex():
    session = make_mock_session("codex", "0.110.0")
    info = detect_caller_from_session(session)
    assert info.provider == "codex"
    assert info.platform == "cli"
    print("[PASS] detect Codex CLI")


def test_detect_gemini():
    session = make_mock_session("gemini-cli", "0.32.1")
    info = detect_caller_from_session(session)
    assert info.provider == "gemini"
    assert info.platform == "cli"
    print("[PASS] detect Gemini CLI")


def test_detect_cursor_ide():
    session = make_mock_session("cursor", "0.50.0")
    info = detect_caller_from_session(session)
    assert info.provider == ""
    assert info.platform == "ide"
    print("[PASS] detect Cursor IDE (no provider exclusion)")


def test_detect_windsurf_ide():
    session = make_mock_session("windsurf", "2.0")
    info = detect_caller_from_session(session)
    assert info.provider == ""
    assert info.platform == "ide"
    print("[PASS] detect Windsurf IDE")


def test_detect_unknown_client():
    session = make_mock_session("my-custom-tool", "1.0")
    info = detect_caller_from_session(session)
    assert info.provider == ""
    assert info.platform == "unknown"
    print("[PASS] detect unknown client")


def test_detect_no_client_params():
    session = MagicMock()
    session.client_params = None
    info = detect_caller_from_session(session)
    assert info.detection_method == "none"
    print("[PASS] detect with no client_params")


def test_priority_config_override():
    """Config override should take priority over session detection."""
    session = make_mock_session("claude-code")
    info = detect_caller(session=session, config_override="codex")
    assert info.provider == "codex"
    assert info.detection_method == "config_override"
    print("[PASS] config override takes priority")


def test_priority_session_over_env():
    """Session detection should take priority over env detection."""
    session = make_mock_session("claude-code")
    info = detect_caller(session=session, config_override="")
    assert info.provider == "claude"
    assert info.detection_method == "mcp_client_info"
    print("[PASS] session takes priority over env")


def test_exclusion_cli_caller():
    """CLI caller should be excluded from routing."""
    caller = CallerInfo(provider="claude", platform="cli")
    excl = get_excluded_providers(caller)
    assert excl == ["claude"]
    print("[PASS] CLI caller excluded")


def test_exclusion_ide_caller():
    """IDE caller should NOT be excluded (they're not dispatch targets)."""
    caller = CallerInfo(provider="", platform="ide")
    excl = get_excluded_providers(caller)
    assert excl == []
    print("[PASS] IDE caller not excluded")


def test_exclusion_unknown_caller():
    caller = CallerInfo()
    excl = get_excluded_providers(caller)
    assert excl == []
    print("[PASS] unknown caller not excluded")


def test_routing_exclusion_scenario():
    """Full scenario: Claude Code calling, task routes to claude → redirect."""
    from vyane.routing import keyword_scores

    task = "Review this code for security vulnerabilities"
    scores = keyword_scores(task)
    route = max(scores, key=lambda k: scores[k])
    assert route == "claude", f"Expected claude route, got {route}"

    caller = CallerInfo(provider="claude", platform="cli")
    excluded = get_excluded_providers(caller)

    actual = route
    if actual in excluded:
        for alt in ["codex", "gemini", "claude"]:
            if alt != actual and alt not in excluded:
                actual = alt
                break

    assert actual != "claude", f"Should not route to caller (claude)"
    assert actual == "codex", f"Expected codex fallback, got {actual}"


def test_routing_no_exclusion_needed():
    """Task routes to different provider than caller → no change."""
    from vyane.routing import keyword_scores

    task = "Implement a binary search algorithm"
    scores = keyword_scores(task)
    route = max(scores, key=lambda k: scores[k])
    assert route == "codex"

    caller = CallerInfo(provider="claude", platform="cli")
    excluded = get_excluded_providers(caller)

    actual = route
    if actual in excluded:
        for alt in ["codex", "gemini", "claude"]:
            if alt != actual and alt not in excluded:
                actual = alt
                break

    assert actual == "codex", "Route should stay as codex"


def test_combined_exclusion():
    """disabled_providers + caller exclusion combined."""
    from vyane.config import MuxConfig

    config = MuxConfig(disabled_providers=["gemini"])
    caller = CallerInfo(provider="claude", platform="cli")

    excluded = list(config.disabled_providers)
    for p in get_excluded_providers(caller):
        if p not in excluded:
            excluded.append(p)

    assert "gemini" in excluded
    assert "claude" in excluded
    assert "codex" not in excluded
    print("[PASS] combined exclusion (disabled + caller)")


def main():
    tests = [
        test_detect_claude_code,
        test_detect_codex,
        test_detect_gemini,
        test_detect_cursor_ide,
        test_detect_windsurf_ide,
        test_detect_unknown_client,
        test_detect_no_client_params,
        test_priority_config_override,
        test_priority_session_over_env,
        test_exclusion_cli_caller,
        test_exclusion_ide_caller,
        test_exclusion_unknown_caller,
        test_routing_exclusion_scenario,
        test_routing_no_exclusion_needed,
        test_combined_exclusion,
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
    print(f"Detection tests: {passed}/{passed + failed} passed")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
