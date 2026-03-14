"""Tests for the Gemini CLI adapter."""

import json

from vyane.adapters.gemini import DEPRECATION_MARKERS, GeminiAdapter


class TestGeminiAdapter:
    def test_provider_name(self):
        a = GeminiAdapter()
        assert a.provider_name == "gemini"

    def test_binary_name(self):
        a = GeminiAdapter()
        assert a._binary_name() == "gemini"


class TestBuildCommand:
    def test_basic(self):
        a = GeminiAdapter()
        cmd = a.build_command("hello", "/tmp")
        # Default sandbox is "read-only" which adds --sandbox
        assert cmd == ["gemini", "--prompt", "hello", "-o", "stream-json", "--sandbox"]

    def test_sandbox_readonly(self):
        a = GeminiAdapter()
        cmd = a.build_command("hi", "/tmp", sandbox="read-only")
        assert "--sandbox" in cmd

    def test_sandbox_sandbox(self):
        a = GeminiAdapter()
        cmd = a.build_command("hi", "/tmp", sandbox="sandbox")
        assert "--sandbox" in cmd

    def test_sandbox_write(self):
        a = GeminiAdapter()
        cmd = a.build_command("hi", "/tmp", sandbox="write")
        assert "--sandbox" not in cmd

    def test_sandbox_full(self):
        a = GeminiAdapter()
        cmd = a.build_command("hi", "/tmp", sandbox="full")
        assert "--sandbox" not in cmd

    def test_with_model(self):
        a = GeminiAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args={"model": "gemini-2.5-pro"})
        assert "--model" in cmd
        assert "gemini-2.5-pro" in cmd

    def test_with_approval_mode(self):
        a = GeminiAdapter()
        cmd = a.build_command(
            "hi", "/tmp", extra_args={"approval_mode": "full-auto"}
        )
        assert "--approval-mode" in cmd
        assert "full-auto" in cmd

    def test_with_session_id(self):
        a = GeminiAdapter()
        cmd = a.build_command("hi", "/tmp", session_id="sess-abc")
        assert "--resume" in cmd
        assert "sess-abc" in cmd

    def test_no_session_id(self):
        a = GeminiAdapter()
        cmd = a.build_command("hi", "/tmp", session_id="")
        assert "--resume" not in cmd

    def test_no_extra_args(self):
        a = GeminiAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args=None)
        assert "--model" not in cmd
        assert "--approval-mode" not in cmd

    def test_empty_extra_args(self):
        a = GeminiAdapter()
        cmd = a.build_command("hi", "/tmp", extra_args={})
        assert "--model" not in cmd


class TestParseOutput:
    def test_assistant_message(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({"type": "message", "role": "assistant", "content": "Hello!"}),
        ]
        text, sid, err = a.parse_output(lines)
        assert text == "Hello!"
        assert sid == ""
        assert err == ""

    def test_user_message_ignored(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({"type": "message", "role": "user", "content": "User input"}),
        ]
        text, sid, err = a.parse_output(lines)
        assert text == ""

    def test_session_id_extraction(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({"session_id": "sid-123", "type": "init"}),
            json.dumps({"type": "message", "role": "assistant", "content": "Hi"}),
        ]
        text, sid, err = a.parse_output(lines)
        assert sid == "sid-123"
        assert text == "Hi"

    def test_content_parts_dict(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({
                "type": "content",
                "parts": [{"text": "Part 1"}, {"text": "Part 2"}],
            }),
        ]
        text, sid, err = a.parse_output(lines)
        assert "Part 1" in text
        assert "Part 2" in text

    def test_content_parts_string(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({"type": "content", "parts": ["raw text"]}),
        ]
        text, sid, err = a.parse_output(lines)
        assert text == "raw text"

    def test_error_message(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({"type": "error", "message": "Something broke"}),
        ]
        text, sid, err = a.parse_output(lines)
        assert err == "Something broke"
        assert text == ""

    def test_fail_message(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({"type": "fail", "error": "Auth failed"}),
        ]
        text, sid, err = a.parse_output(lines)
        assert err == "Auth failed"

    def test_deprecation_filtered(self):
        a = GeminiAdapter()
        lines = [
            "DeprecationWarning: --prompt is deprecated",
            json.dumps({"type": "message", "role": "assistant", "content": "OK"}),
        ]
        text, sid, err = a.parse_output(lines)
        assert text == "OK"

    def test_non_json_lines_skipped(self):
        a = GeminiAdapter()
        lines = [
            "plain text banner",
            json.dumps({"type": "message", "role": "assistant", "content": "Result"}),
        ]
        text, sid, err = a.parse_output(lines)
        assert text == "Result"

    def test_empty_output(self):
        a = GeminiAdapter()
        text, sid, err = a.parse_output([])
        assert text == ""
        assert sid == ""
        assert err == ""

    def test_first_session_id_wins(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({"session_id": "first"}),
            json.dumps({"session_id": "second"}),
        ]
        text, sid, err = a.parse_output(lines)
        assert sid == "first"

    def test_empty_content_message(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({"type": "message", "role": "assistant", "content": ""}),
        ]
        text, sid, err = a.parse_output(lines)
        assert text == ""


class TestParseTokenUsage:
    def test_with_usage_metadata(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 50,
                    "totalTokenCount": 150,
                }
            }),
        ]
        usage = a.parse_token_usage(lines)
        assert usage is not None
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.total_tokens == 150

    def test_total_computed(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({
                "usageMetadata": {
                    "promptTokenCount": 80,
                    "candidatesTokenCount": 20,
                    "totalTokenCount": 0,
                }
            }),
        ]
        usage = a.parse_token_usage(lines)
        assert usage is not None
        assert usage.total_tokens == 100

    def test_no_usage_metadata(self):
        a = GeminiAdapter()
        lines = [json.dumps({"type": "message", "content": "hi"})]
        usage = a.parse_token_usage(lines)
        assert usage is None

    def test_invalid_usage_metadata(self):
        a = GeminiAdapter()
        lines = [json.dumps({"usageMetadata": "not a dict"})]
        usage = a.parse_token_usage(lines)
        assert usage is None

    def test_all_zeros(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({
                "usageMetadata": {
                    "promptTokenCount": 0,
                    "candidatesTokenCount": 0,
                    "totalTokenCount": 0,
                }
            }),
        ]
        usage = a.parse_token_usage(lines)
        assert usage is None

    def test_last_event_wins(self):
        a = GeminiAdapter()
        lines = [
            json.dumps({
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 15,
                }
            }),
            json.dumps({
                "usageMetadata": {
                    "promptTokenCount": 200,
                    "candidatesTokenCount": 100,
                    "totalTokenCount": 300,
                }
            }),
        ]
        usage = a.parse_token_usage(lines)
        # Iterates in reverse, so last event is checked first
        assert usage.total_tokens == 300

    def test_non_json_lines_skipped(self):
        a = GeminiAdapter()
        usage_data = {
            "usageMetadata": {
                "promptTokenCount": 5,
                "candidatesTokenCount": 3,
                "totalTokenCount": 8,
            }
        }
        lines = ["not json", json.dumps(usage_data)]
        usage = a.parse_token_usage(lines)
        assert usage is not None
        assert usage.total_tokens == 8

    def test_in_registry(self):
        from vyane.adapters import ADAPTERS

        assert "gemini" in ADAPTERS
        assert ADAPTERS["gemini"] is GeminiAdapter


class TestDeprecationMarkers:
    def test_markers_defined(self):
        assert len(DEPRECATION_MARKERS) > 0
        assert "deprecated" in DEPRECATION_MARKERS
