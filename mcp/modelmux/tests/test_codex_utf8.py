"""Tests for Codex adapter UTF-8 workaround."""

import os
import tempfile

from modelmux.adapters.codex import (
    CodexAdapter,
    _create_ascii_symlink,
    _needs_ascii_workaround,
)


# --- _needs_ascii_workaround ---


def test_ascii_path_no_workaround():
    assert _needs_ascii_workaround("/tmp/some/path") is False


def test_non_ascii_path_needs_workaround():
    assert _needs_ascii_workaround("/Users/maple/我的云端硬盘/dev") is True


def test_mixed_path_needs_workaround():
    assert _needs_ascii_workaround("/Users/maple/Données/project") is True


def test_empty_path_no_workaround():
    assert _needs_ascii_workaround("") is False


# --- _create_ascii_symlink ---


def test_symlink_created_and_resolves():
    target = tempfile.mkdtemp()
    try:
        link = _create_ascii_symlink(target)
        assert os.path.islink(link)
        assert os.path.realpath(link) == os.path.realpath(target)
        # Path should be pure ASCII
        assert _needs_ascii_workaround(link) is False
        # Cleanup
        os.unlink(link)
        os.rmdir(os.path.dirname(link))
    finally:
        os.rmdir(target)


def test_symlink_prefix():
    target = tempfile.mkdtemp()
    try:
        link = _create_ascii_symlink(target)
        parent = os.path.dirname(link)
        assert "mux-codex-" in os.path.basename(parent)
        os.unlink(link)
        os.rmdir(parent)
    finally:
        os.rmdir(target)


# --- CodexAdapter.build_command uses workdir as-is ---


def test_build_command_preserves_workdir():
    adapter = CodexAdapter()
    cmd = adapter.build_command("hello", "/some/path")
    assert "/some/path" in cmd


# --- CodexAdapter.run workaround integration ---


def test_adapter_has_run_override():
    """Verify CodexAdapter overrides run (not just inherits)."""
    import inspect

    assert "run" in CodexAdapter.__dict__
    sig = inspect.signature(CodexAdapter.run)
    assert "workdir" in sig.parameters
