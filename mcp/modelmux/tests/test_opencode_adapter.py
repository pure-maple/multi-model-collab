"""Tests for the opencode CLI adapter."""

from unittest.mock import patch

from vyane.adapters.opencode import OpencodeAdapter


class TestOpencodeAdapter:
    def test_provider_name(self):
        a = OpencodeAdapter()
        assert a.provider_name == "opencode"

    def test_binary_name(self):
        a = OpencodeAdapter()
        assert a._binary_name() == "opencode"

    def test_check_available_found(self):
        a = OpencodeAdapter()
        with patch("shutil.which", return_value="/usr/local/bin/opencode"):
            assert a.check_available() is True

    def test_check_available_not_found(self):
        a = OpencodeAdapter()
        with patch("shutil.which", return_value=None):
            assert a.check_available() is False


class TestBuildCommand:
    def test_basic(self):
        a = OpencodeAdapter()
        cmd = a.build_command("hello world", "/tmp")
        assert cmd == ["opencode", "-p", "hello world"]

    def test_with_model(self):
        a = OpencodeAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args={"model": "gpt-4o"})
        assert cmd == ["opencode", "-p", "hi", "--model", "gpt-4o"]

    def test_with_provider(self):
        a = OpencodeAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args={"provider": "anthropic"})
        assert cmd == ["opencode", "-p", "hi", "--provider", "anthropic"]

    def test_with_model_and_provider(self):
        a = OpencodeAdapter()
        cmd = a.build_command(
            "hi", "/tmp", extra_args={"model": "claude-4-sonnet", "provider": "anthropic"}
        )
        assert "--model" in cmd
        assert "claude-4-sonnet" in cmd
        assert "--provider" in cmd
        assert "anthropic" in cmd

    def test_with_session_id(self):
        a = OpencodeAdapter()
        cmd = a.build_command("hi", "/tmp", session_id="sess-123")
        assert "--resume" in cmd
        assert "sess-123" in cmd

    def test_no_session_id(self):
        a = OpencodeAdapter()
        cmd = a.build_command("hi", "/tmp", session_id="")
        assert "--resume" not in cmd

    def test_no_extra_args(self):
        a = OpencodeAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args=None)
        assert cmd == ["opencode", "-p", "hi"]

    def test_empty_extra_args(self):
        a = OpencodeAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args={})
        assert cmd == ["opencode", "-p", "hi"]

    def test_model_and_session(self):
        a = OpencodeAdapter()
        cmd = a.build_command(
            "task", "/work", session_id="s1", extra_args={"model": "gpt-4o"}
        )
        assert cmd == [
            "opencode", "-p", "task", "--model", "gpt-4o", "--resume", "s1"
        ]

    def test_sandbox_ignored(self):
        """opencode adapter does not use sandbox flags."""
        a = OpencodeAdapter()
        cmd = a.build_command("hi", "/tmp", sandbox="full")
        assert "--sandbox" not in cmd
        assert cmd == ["opencode", "-p", "hi"]


class TestParseOutput:
    def test_plain_text(self):
        a = OpencodeAdapter()
        lines = ["Hello!", "How can I help?"]
        text, sid, err = a.parse_output(lines)
        assert text == "Hello!\nHow can I help?"
        assert sid == ""
        assert err == ""

    def test_session_line_uppercase(self):
        a = OpencodeAdapter()
        lines = ["Session: abc-123", "Output here"]
        text, sid, err = a.parse_output(lines)
        assert sid == "abc-123"
        assert "Session:" not in text
        assert "Output here" in text

    def test_session_line_lowercase(self):
        a = OpencodeAdapter()
        lines = ["session: xyz-789", "Result"]
        text, sid, err = a.parse_output(lines)
        assert sid == "xyz-789"
        assert "Result" in text

    def test_empty_output(self):
        a = OpencodeAdapter()
        text, sid, err = a.parse_output([])
        assert text == ""
        assert sid == ""
        assert err == ""

    def test_session_no_value(self):
        a = OpencodeAdapter()
        lines = ["Session:", "text"]
        text, sid, err = a.parse_output(lines)
        assert sid == ""
        assert "text" in text

    def test_multiple_session_lines(self):
        a = OpencodeAdapter()
        lines = ["Session: first", "Session: second", "output"]
        text, sid, err = a.parse_output(lines)
        # Last session line wins (overwrites)
        assert sid == "second"

    def test_multiline_output(self):
        a = OpencodeAdapter()
        lines = [
            "Here is the analysis:",
            "1. First point",
            "2. Second point",
            "Done.",
        ]
        text, sid, err = a.parse_output(lines)
        assert "First point" in text
        assert "Second point" in text
        assert text.count("\n") == 3

    def test_error_always_empty(self):
        """opencode adapter returns empty error (plain text parser)."""
        a = OpencodeAdapter()
        lines = ["ERROR: something went wrong"]
        text, sid, err = a.parse_output(lines)
        assert err == ""
        assert "ERROR: something went wrong" in text


class TestRegistry:
    def test_in_registry(self):
        from vyane.adapters import ADAPTERS

        assert "opencode" in ADAPTERS
        assert ADAPTERS["opencode"] is OpencodeAdapter
