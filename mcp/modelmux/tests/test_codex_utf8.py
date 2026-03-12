"""Tests for Codex adapter UTF-8 workaround."""

import os
import tempfile

from modelmux.adapters.codex import (
    CodexAdapter,
    _create_ascii_symlink,
    _find_git_dir,
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


# --- _find_git_dir ---


def test_find_git_dir_in_repo():
    """Should find .git directory in an actual git repo."""
    # Use the modelmux repo itself as test subject
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = _find_git_dir(src_dir)
    # Should find a .git dir somewhere above tests/
    assert result is not None
    assert os.path.exists(result)


def test_find_git_dir_in_tmp():
    """A random tmpdir has no .git — should return None."""
    with tempfile.TemporaryDirectory() as d:
        assert _find_git_dir(d) is None


def test_find_git_dir_with_git_directory():
    """Should find .git when it's a directory."""
    with tempfile.TemporaryDirectory() as d:
        git_dir = os.path.join(d, ".git")
        os.mkdir(git_dir)
        result = _find_git_dir(d)
        assert result == os.path.realpath(git_dir)


def test_find_git_dir_with_git_file():
    """Should follow .git file pointer (worktree style)."""
    with tempfile.TemporaryDirectory() as d:
        real_git = os.path.join(d, "real-git-dir")
        os.mkdir(real_git)
        sub = os.path.join(d, "sub")
        os.mkdir(sub)
        git_file = os.path.join(sub, ".git")
        with open(git_file, "w") as f:
            f.write(f"gitdir: {real_git}\n")
        result = _find_git_dir(sub)
        assert result == os.path.realpath(real_git)


def test_find_git_dir_with_relative_git_file():
    """Relative gitdir pointers should be resolved from the .git file location."""
    with tempfile.TemporaryDirectory() as d:
        real_git = os.path.join(d, "real-git-dir")
        os.mkdir(real_git)
        nested = os.path.join(d, "nested")
        os.mkdir(nested)
        sub = os.path.join(nested, "sub")
        os.mkdir(sub)
        git_file = os.path.join(sub, ".git")
        with open(git_file, "w") as f:
            f.write("gitdir: ../../real-git-dir\n")
        result = _find_git_dir(sub)
        assert result == os.path.realpath(real_git)


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


def test_run_sets_pwd_env_for_non_ascii():
    """When workdir has non-ASCII chars, PWD env var should be set."""
    import asyncio
    from unittest.mock import patch

    adapter = CodexAdapter()
    captured_env = {}

    async def mock_super_run(self_, **kwargs):
        captured_env.update(kwargs.get("env_overrides") or {})
        from modelmux.adapters.base import AdapterResult

        return AdapterResult(provider="codex", status="success", output="ok")

    with patch.object(
        CodexAdapter.__bases__[0],
        "run",
        new=mock_super_run,
    ):
        asyncio.run(
            adapter.run(
                prompt="test",
                workdir="/Users/maple/我的云端硬盘/dev",
            )
        )

    assert "PWD" in captured_env
    assert _needs_ascii_workaround(captured_env["PWD"]) is False


def test_run_sets_git_env_for_non_ascii_in_repo():
    """GIT_WORK_TREE and GIT_DIR should be set for non-ASCII git repos."""
    import asyncio
    from unittest.mock import patch

    adapter = CodexAdapter()
    captured = {}

    async def mock_super_run(self_, **kwargs):
        captured.update(kwargs.get("env_overrides") or {})
        captured["workdir"] = kwargs.get("workdir", "")
        from modelmux.adapters.base import AdapterResult

        return AdapterResult(provider="codex", status="success", output="ok")

    # Create a non-ASCII dir with a .git inside
    with tempfile.TemporaryDirectory() as base:
        non_ascii = os.path.join(base, "我的项目")
        os.mkdir(non_ascii)
        os.mkdir(os.path.join(non_ascii, ".git"))

        with patch.object(CodexAdapter.__bases__[0], "run", new=mock_super_run):
            asyncio.run(adapter.run(prompt="test", workdir=non_ascii))

    assert "GIT_WORK_TREE" in captured
    assert "GIT_DIR" in captured
    assert _needs_ascii_workaround(captured["GIT_WORK_TREE"]) is False
    assert captured["GIT_DIR"] == os.path.realpath(os.path.join(non_ascii, ".git"))


def test_run_no_git_env_without_git_dir():
    """Non-ASCII dir without .git should not set GIT_* env vars."""
    import asyncio
    from unittest.mock import patch

    adapter = CodexAdapter()
    captured = {}

    async def mock_super_run(self_, **kwargs):
        captured.update(kwargs.get("env_overrides") or {})
        from modelmux.adapters.base import AdapterResult

        return AdapterResult(provider="codex", status="success", output="ok")

    with tempfile.TemporaryDirectory() as base:
        non_ascii = os.path.join(base, "数据目录")
        os.mkdir(non_ascii)

        with patch.object(CodexAdapter.__bases__[0], "run", new=mock_super_run):
            asyncio.run(adapter.run(prompt="test", workdir=non_ascii))

    assert "PWD" in captured
    assert "GIT_WORK_TREE" not in captured
    assert "GIT_DIR" not in captured


def test_run_preserves_existing_env_overrides():
    """PWD should be added without clobbering existing env_overrides."""
    import asyncio
    from unittest.mock import patch

    adapter = CodexAdapter()
    captured_env = {}

    async def mock_super_run(self_, **kwargs):
        captured_env.update(kwargs.get("env_overrides") or {})
        from modelmux.adapters.base import AdapterResult

        return AdapterResult(provider="codex", status="success", output="ok")

    with patch.object(
        CodexAdapter.__bases__[0],
        "run",
        new=mock_super_run,
    ):
        asyncio.run(
            adapter.run(
                prompt="test",
                workdir="/Users/maple/我的云端硬盘/dev",
                env_overrides={"MY_VAR": "hello"},
            )
        )

    assert captured_env.get("MY_VAR") == "hello"
    assert "PWD" in captured_env


def test_run_no_pwd_for_ascii_workdir():
    """ASCII workdir should not get PWD override."""
    import asyncio
    from unittest.mock import patch

    adapter = CodexAdapter()
    captured_env = {}

    async def mock_super_run(self_, **kwargs):
        captured_env.update(kwargs.get("env_overrides") or {})
        from modelmux.adapters.base import AdapterResult

        return AdapterResult(provider="codex", status="success", output="ok")

    with patch.object(
        CodexAdapter.__bases__[0],
        "run",
        new=mock_super_run,
    ):
        asyncio.run(adapter.run(prompt="test", workdir="/tmp/ascii/path"))

    assert "PWD" not in captured_env
