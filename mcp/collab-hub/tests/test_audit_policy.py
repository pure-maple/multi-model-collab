"""Unit tests for audit logging and policy engine.

Run with: cd mcp/collab-hub && uv run python tests/test_audit_policy.py
"""

import datetime
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "src")

from collab_hub.audit import AuditEntry, _audit_file, get_audit_stats, log_dispatch
from collab_hub.policy import Policy, PolicyResult, check_policy, load_policy


# === Audit Tests ===


def test_audit_log_write():
    """Test writing an audit entry to a temp file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_file = Path(tmpdir) / "audit.jsonl"
        with patch("collab_hub.audit._audit_file", return_value=fake_file):
            with patch("collab_hub.audit._audit_dir", return_value=Path(tmpdir)):
                entry = AuditEntry(
                    timestamp=datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                    provider="codex",
                    task_summary="Implement binary search",
                    status="success",
                    duration_seconds=5.2,
                    caller="claude-code",
                    caller_platform="cli",
                    sandbox="read-only",
                )
                log_dispatch(entry)

                assert fake_file.exists()
                line = fake_file.read_text().strip()
                data = json.loads(line)
                assert data["provider"] == "codex"
                assert data["status"] == "success"
                assert data["caller"] == "claude-code"
    print("[PASS] audit log write")


def test_audit_stats():
    """Test audit stats calculation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_file = Path(tmpdir) / "audit.jsonl"
        with patch("collab_hub.audit._audit_file", return_value=fake_file):
            with patch("collab_hub.audit._audit_dir", return_value=Path(tmpdir)):
                ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
                for i, (prov, status) in enumerate(
                    [
                        ("codex", "success"),
                        ("codex", "success"),
                        ("gemini", "error"),
                        ("claude", "success"),
                    ]
                ):
                    log_dispatch(
                        AuditEntry(
                            timestamp=ts,
                            provider=prov,
                            status=status,
                            task_summary=f"task {i}",
                        )
                    )

                stats = get_audit_stats()
                assert stats["total_entries"] == 4
                assert stats["by_provider"]["codex"] == 2
                assert stats["by_provider"]["gemini"] == 1
                assert stats["by_status"]["success"] == 3
                assert stats["by_status"]["error"] == 1
    print("[PASS] audit stats")


# === Policy Tests ===


def test_policy_default_allows_all():
    """Default policy (no file) should allow everything."""
    policy = Policy()
    result = check_policy(policy, provider="codex", sandbox="read-only")
    assert result.allowed
    print("[PASS] default policy allows all")


def test_policy_allowlist():
    """Only allowed providers should pass."""
    policy = Policy(allowed_providers=["codex", "gemini"])

    r1 = check_policy(policy, provider="codex")
    assert r1.allowed

    r2 = check_policy(policy, provider="claude")
    assert not r2.allowed
    assert "allowlist" in r2.reason
    print("[PASS] provider allowlist")


def test_policy_blocklist():
    """Blocked providers should be denied."""
    policy = Policy(blocked_providers=["gemini"])

    r1 = check_policy(policy, provider="codex")
    assert r1.allowed

    r2 = check_policy(policy, provider="gemini")
    assert not r2.allowed
    assert "blocked" in r2.reason
    print("[PASS] provider blocklist")


def test_policy_sandbox_block():
    """Blocked sandbox levels should be denied."""
    policy = Policy(blocked_sandboxes=["full"])

    r1 = check_policy(policy, provider="codex", sandbox="read-only")
    assert r1.allowed

    r2 = check_policy(policy, provider="codex", sandbox="full")
    assert not r2.allowed
    assert "full" in r2.reason
    print("[PASS] sandbox block")


def test_policy_timeout_cap():
    """Timeout exceeding cap should be denied."""
    policy = Policy(max_timeout=120)

    r1 = check_policy(policy, provider="codex", timeout=60)
    assert r1.allowed

    r2 = check_policy(policy, provider="codex", timeout=300)
    assert not r2.allowed
    assert "120" in r2.reason
    print("[PASS] timeout cap")


def test_policy_rate_limit_hour():
    """Hourly rate limit should be enforced."""
    policy = Policy(max_calls_per_hour=10)

    r1 = check_policy(policy, provider="codex", calls_last_hour=5)
    assert r1.allowed

    r2 = check_policy(policy, provider="codex", calls_last_hour=10)
    assert not r2.allowed
    assert "hour" in r2.reason
    print("[PASS] rate limit per hour")


def test_policy_rate_limit_day():
    """Daily rate limit should be enforced."""
    policy = Policy(max_calls_per_day=100)

    r1 = check_policy(policy, provider="codex", calls_last_day=50)
    assert r1.allowed

    r2 = check_policy(policy, provider="codex", calls_last_day=100)
    assert not r2.allowed
    assert "24 hours" in r2.reason
    print("[PASS] rate limit per day")


def test_policy_load_from_file():
    """Test loading policy from a JSON file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        policy_file = Path(tmpdir) / "policy.json"
        policy_file.write_text(
            json.dumps(
                {
                    "blocked_providers": ["gemini"],
                    "blocked_sandboxes": ["full"],
                    "max_timeout": 600,
                    "max_calls_per_hour": 30,
                }
            )
        )
        with patch("collab_hub.policy._policy_file", return_value=policy_file):
            policy = load_policy()
            assert "gemini" in policy.blocked_providers
            assert "full" in policy.blocked_sandboxes
            assert policy.max_timeout == 600
            assert policy.max_calls_per_hour == 30
    print("[PASS] load policy from file")


def test_policy_combined():
    """Test multiple policy constraints together."""
    policy = Policy(
        blocked_providers=["gemini"],
        blocked_sandboxes=["full"],
        max_timeout=120,
        max_calls_per_hour=5,
    )

    # Good request
    r = check_policy(
        policy, provider="codex", sandbox="read-only", timeout=60, calls_last_hour=2
    )
    assert r.allowed

    # Bad provider
    r = check_policy(policy, provider="gemini", sandbox="read-only")
    assert not r.allowed

    # Bad sandbox
    r = check_policy(policy, provider="codex", sandbox="full")
    assert not r.allowed

    # Bad timeout
    r = check_policy(policy, provider="codex", timeout=300)
    assert not r.allowed

    # Rate limited
    r = check_policy(policy, provider="codex", calls_last_hour=5)
    assert not r.allowed

    print("[PASS] combined policy checks")


def main():
    tests = [
        test_audit_log_write,
        test_audit_stats,
        test_policy_default_allows_all,
        test_policy_allowlist,
        test_policy_blocklist,
        test_policy_sandbox_block,
        test_policy_timeout_cap,
        test_policy_rate_limit_hour,
        test_policy_rate_limit_day,
        test_policy_load_from_file,
        test_policy_combined,
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
    print(f"Audit & Policy tests: {passed}/{passed + failed} passed")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
