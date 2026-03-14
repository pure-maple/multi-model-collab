"""Tests for the Claude CLI adapter."""

from vyane.adapters.claude import ClaudeAdapter


class TestClaudeAdapter:
    def test_provider_name(self):
        a = ClaudeAdapter()
        assert a.provider_name == "claude"

    def test_binary_name(self):
        a = ClaudeAdapter()
        assert a._binary_name() == "claude"


class TestBuildCommand:
    def test_basic(self):
        a = ClaudeAdapter()
        cmd = a.build_command("hello world", "/tmp")
        assert cmd == ["claude", "-p", "hello world"]

    def test_with_model(self):
        a = ClaudeAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args={"model": "opus"})
        assert cmd == ["claude", "-p", "hi", "--model", "opus"]

    def test_with_allowed_tools(self):
        a = ClaudeAdapter()
        cmd = a.build_command(
            "hi", "/tmp", extra_args={"allowed_tools": ["Read", "Edit"]}
        )
        assert "--allowedTools" in cmd
        idx = cmd.index("--allowedTools")
        assert cmd[idx + 1] == "Read"
        assert cmd[idx + 2] == "--allowedTools"
        assert cmd[idx + 3] == "Edit"

    def test_with_session_id(self):
        a = ClaudeAdapter()
        cmd = a.build_command("hi", "/tmp", session_id="sess-123")
        assert "--resume" in cmd
        assert "sess-123" in cmd

    def test_no_session_id(self):
        a = ClaudeAdapter()
        cmd = a.build_command("hi", "/tmp", session_id="")
        assert "--resume" not in cmd

    def test_no_extra_args(self):
        a = ClaudeAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args=None)
        assert cmd == ["claude", "-p", "hi"]

    def test_empty_extra_args(self):
        a = ClaudeAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args={})
        assert cmd == ["claude", "-p", "hi"]

    def test_model_and_session(self):
        a = ClaudeAdapter()
        cmd = a.build_command(
            "task", "/work", session_id="s1", extra_args={"model": "sonnet"}
        )
        assert cmd == ["claude", "-p", "task", "--model", "sonnet", "--resume", "s1"]


class TestParseOutput:
    def test_plain_text(self):
        a = ClaudeAdapter()
        lines = ["Hello!", "How can I help?"]
        text, sid, err = a.parse_output(lines)
        assert text == "Hello!\nHow can I help?"
        assert sid == ""
        assert err == ""

    def test_session_line_uppercase(self):
        a = ClaudeAdapter()
        lines = ["Session: abc-123", "Output here"]
        text, sid, err = a.parse_output(lines)
        assert sid == "abc-123"
        assert "Session:" not in text
        assert "Output here" in text

    def test_session_line_lowercase(self):
        a = ClaudeAdapter()
        lines = ["session: xyz-789", "Result"]
        text, sid, err = a.parse_output(lines)
        assert sid == "xyz-789"
        assert "Result" in text

    def test_empty_output(self):
        a = ClaudeAdapter()
        text, sid, err = a.parse_output([])
        assert text == ""
        assert sid == ""
        assert err == ""

    def test_session_no_value(self):
        a = ClaudeAdapter()
        lines = ["Session:", "text"]
        text, sid, err = a.parse_output(lines)
        assert sid == ""
        assert "text" in text

    def test_multiple_session_lines(self):
        a = ClaudeAdapter()
        lines = ["Session: first", "Session: second", "output"]
        text, sid, err = a.parse_output(lines)
        # Last session line wins (overwrites)
        assert sid == "second"

    def test_in_registry(self):
        from vyane.adapters import ADAPTERS

        assert "claude" in ADAPTERS
        assert ADAPTERS["claude"] is ClaudeAdapter
