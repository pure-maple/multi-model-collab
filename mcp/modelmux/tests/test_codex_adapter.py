"""Tests for the Codex CLI adapter (parse_output, parse_token_usage, build_command)."""

import json
import os

from vyane.adapters.codex import (
    RECONNECT_RE,
    CodexAdapter,
    _create_ascii_symlink,
    _find_git_dir,
    _needs_ascii_workaround,
)


class TestNeedsAsciiWorkaround:
    def test_ascii_path(self):
        assert _needs_ascii_workaround("/tmp/work") is False

    def test_unicode_path(self):
        assert _needs_ascii_workaround("/tmp/我的云端") is True

    def test_empty_path(self):
        assert _needs_ascii_workaround("") is False


class TestCreateAsciiSymlink:
    def test_creates_symlink(self, tmp_path):
        target = str(tmp_path)
        link = _create_ascii_symlink(target)
        try:
            assert os.path.islink(link)
            assert os.readlink(link) == target
            assert link.endswith("workdir")
        finally:
            os.unlink(link)
            os.rmdir(os.path.dirname(link))


class TestFindGitDir:
    def test_finds_dot_git_dir(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        result = _find_git_dir(str(tmp_path))
        assert result == str(git_dir)

    def test_finds_git_in_parent(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        result = _find_git_dir(str(sub))
        assert result == str(git_dir)

    def test_no_git_dir(self, tmp_path):
        sub = tmp_path / "isolated"
        sub.mkdir()
        result = _find_git_dir(str(sub))
        assert result is None

    def test_git_file_worktree(self, tmp_path):
        real_git = tmp_path / "real.git"
        real_git.mkdir()
        wt = tmp_path / "worktree"
        wt.mkdir()
        git_file = wt / ".git"
        git_file.write_text(f"gitdir: {real_git}")
        result = _find_git_dir(str(wt))
        assert result == str(real_git)

    def test_git_file_invalid(self, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        git_file = wt / ".git"
        git_file.write_text("not a gitdir pointer")
        result = _find_git_dir(str(wt))
        assert result is None


class TestReconnectRegex:
    def test_matches_reconnect(self):
        assert RECONNECT_RE.match("Reconnecting...   1/5")

    def test_no_match_normal(self):
        assert RECONNECT_RE.match("Normal output") is None


class TestBuildCommand:
    def test_basic(self):
        a = CodexAdapter()
        cmd = a.build_command("do stuff", "/work")
        assert cmd[0] == "codex"
        assert "exec" in cmd
        assert "--json" in cmd
        assert "--cd" in cmd
        assert "/work" in cmd
        assert "do stuff" in cmd

    def test_sandbox_readonly(self):
        a = CodexAdapter()
        cmd = a.build_command("x", "/w", sandbox="read-only")
        idx = cmd.index("--sandbox")
        assert cmd[idx + 1] == "read-only"

    def test_sandbox_write(self):
        a = CodexAdapter()
        cmd = a.build_command("x", "/w", sandbox="write")
        idx = cmd.index("--sandbox")
        assert cmd[idx + 1] == "workspace-write"

    def test_sandbox_full(self):
        a = CodexAdapter()
        cmd = a.build_command("x", "/w", sandbox="full")
        idx = cmd.index("--sandbox")
        assert cmd[idx + 1] == "danger-full-access"

    def test_sandbox_unknown_defaults_readonly(self):
        a = CodexAdapter()
        cmd = a.build_command("x", "/w", sandbox="unknown")
        idx = cmd.index("--sandbox")
        assert cmd[idx + 1] == "read-only"

    def test_with_model(self):
        a = CodexAdapter()
        cmd = a.build_command("x", "/w", extra_args={"model": "gpt-5"})
        assert "--model" in cmd
        assert "gpt-5" in cmd

    def test_with_profile(self):
        a = CodexAdapter()
        cmd = a.build_command("x", "/w", extra_args={"profile": "fast"})
        assert "--profile" in cmd
        assert "fast" in cmd

    def test_with_reasoning_effort(self):
        a = CodexAdapter()
        cmd = a.build_command("x", "/w", extra_args={"reasoning_effort": "xhigh"})
        assert "--reasoning-effort" in cmd
        assert "xhigh" in cmd

    def test_with_images(self):
        a = CodexAdapter()
        cmd = a.build_command(
            "x", "/w", extra_args={"image": ["/tmp/a.png", "/tmp/b.png"]}
        )
        assert cmd.count("--image") == 2

    def test_with_session_id(self):
        a = CodexAdapter()
        cmd = a.build_command("x", "/w", session_id="thread-abc")
        assert "resume" in cmd
        assert "thread-abc" in cmd

    def test_no_session_id(self):
        a = CodexAdapter()
        cmd = a.build_command("x", "/w", session_id="")
        assert "resume" not in cmd

    def test_prompt_after_double_dash(self):
        a = CodexAdapter()
        cmd = a.build_command("my prompt", "/w")
        dd_idx = cmd.index("--")
        assert cmd[dd_idx + 1] == "my prompt"


class TestParseOutput:
    def test_agent_message(self):
        a = CodexAdapter()
        lines = [
            json.dumps({
                "item": {"type": "agent_message", "text": "Done!"},
                "thread_id": "t1",
            }),
        ]
        text, tid, err = a.parse_output(lines)
        assert text == "Done!"
        assert tid == "t1"
        assert err == ""

    def test_multiple_messages(self):
        a = CodexAdapter()
        lines = [
            json.dumps({"item": {"type": "agent_message", "text": "Part 1"}}),
            json.dumps({"item": {"type": "agent_message", "text": "Part 2"}}),
        ]
        text, tid, err = a.parse_output(lines)
        assert text == "Part 1\nPart 2"

    def test_error_event(self):
        a = CodexAdapter()
        lines = [
            json.dumps({"type": "error", "message": "rate limited"}),
        ]
        text, tid, err = a.parse_output(lines)
        assert err == "rate limited"
        assert text == ""

    def test_fail_event(self):
        a = CodexAdapter()
        lines = [
            json.dumps({"type": "fail", "error": "timeout"}),
        ]
        text, tid, err = a.parse_output(lines)
        assert err == "timeout"

    def test_reconnect_filtered(self):
        a = CodexAdapter()
        lines = [
            "Reconnecting...   1/5",
            json.dumps({"item": {"type": "agent_message", "text": "OK"}}),
        ]
        text, tid, err = a.parse_output(lines)
        assert text == "OK"

    def test_non_json_skipped(self):
        a = CodexAdapter()
        lines = ["banner text", "another line"]
        text, tid, err = a.parse_output(lines)
        assert text == ""

    def test_empty_output(self):
        a = CodexAdapter()
        text, tid, err = a.parse_output([])
        assert text == ""
        assert tid == ""
        assert err == ""

    def test_first_thread_id_wins(self):
        a = CodexAdapter()
        lines = [
            json.dumps({"thread_id": "first", "item": {"type": "init"}}),
            json.dumps({"thread_id": "second", "item": {"type": "init"}}),
        ]
        text, tid, err = a.parse_output(lines)
        assert tid == "first"

    def test_empty_agent_message_text(self):
        a = CodexAdapter()
        lines = [
            json.dumps({"item": {"type": "agent_message", "text": ""}}),
        ]
        text, tid, err = a.parse_output(lines)
        assert text == ""


class TestParseTokenUsage:
    def test_turn_completed(self):
        a = CodexAdapter()
        lines = [
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 200,
                    "total_tokens": 700,
                },
            }),
        ]
        usage = a.parse_token_usage(lines)
        assert usage is not None
        assert usage.input_tokens == 500
        assert usage.output_tokens == 200
        assert usage.total_tokens == 700

    def test_total_computed_when_zero(self):
        a = CodexAdapter()
        lines = [
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 0,
                },
            }),
        ]
        usage = a.parse_token_usage(lines)
        assert usage.total_tokens == 150

    def test_non_turn_completed_skipped(self):
        a = CodexAdapter()
        lines = [
            json.dumps({
                "type": "message",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            }),
        ]
        usage = a.parse_token_usage(lines)
        assert usage is None

    def test_no_usage_field(self):
        a = CodexAdapter()
        lines = [json.dumps({"type": "turn.completed"})]
        usage = a.parse_token_usage(lines)
        assert usage is None

    def test_invalid_usage_type(self):
        a = CodexAdapter()
        lines = [json.dumps({"type": "turn.completed", "usage": "bad"})]
        usage = a.parse_token_usage(lines)
        assert usage is None

    def test_all_zeros(self):
        a = CodexAdapter()
        lines = [
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            }),
        ]
        usage = a.parse_token_usage(lines)
        assert usage is None

    def test_last_event_wins(self):
        a = CodexAdapter()
        lines = [
            json.dumps({
                "type": "turn.completed",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            }),
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 400,
                    "output_tokens": 300,
                    "total_tokens": 700,
                },
            }),
        ]
        usage = a.parse_token_usage(lines)
        assert usage.total_tokens == 700

    def test_non_json_skipped(self):
        a = CodexAdapter()
        lines = [
            "not json",
            json.dumps({
                "type": "turn.completed",
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }),
        ]
        usage = a.parse_token_usage(lines)
        assert usage.total_tokens == 2

    def test_in_registry(self):
        from vyane.adapters import ADAPTERS

        assert "codex" in ADAPTERS
        assert ADAPTERS["codex"] is CodexAdapter
