"""Tests for the base adapter module (AdapterResult, TokenUsage, utilities)."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from modelmux.adapters.base import (
    AdapterResult,
    BaseAdapter,
    TokenUsage,
    is_turn_completed,
    sanitize_extra_args,
    stream_subprocess,
)


class TestTokenUsage:
    def test_defaults(self):
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0
        assert u.total_tokens == 0

    def test_to_dict(self):
        u = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)
        d = u.to_dict()
        assert d == {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }


class TestAdapterResult:
    def test_defaults(self):
        r = AdapterResult()
        assert r.run_id == ""
        assert r.provider == ""
        assert r.status == "error"
        assert r.summary == ""
        assert r.output == ""
        assert r.session_id == ""
        assert r.duration_seconds == 0.0
        assert r.error is None
        assert r.token_usage is None

    def test_to_dict_basic(self):
        r = AdapterResult(
            run_id="abc",
            provider="codex",
            status="success",
            summary="Done",
            output="Full output",
            session_id="s1",
            duration_seconds=5.123,
        )
        d = r.to_dict()
        assert d["run_id"] == "abc"
        assert d["provider"] == "codex"
        assert d["status"] == "success"
        assert d["duration_seconds"] == 5.1
        assert "error" not in d
        assert "token_usage" not in d

    def test_to_dict_with_error(self):
        r = AdapterResult(error="something broke")
        d = r.to_dict()
        assert d["error"] == "something broke"

    def test_to_dict_with_token_usage(self):
        r = AdapterResult(
            token_usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        )
        d = r.to_dict()
        assert d["token_usage"]["total_tokens"] == 15

    def test_to_dict_no_error_no_token(self):
        r = AdapterResult(error=None, token_usage=None)
        d = r.to_dict()
        assert "error" not in d
        assert "token_usage" not in d


class TestIsTurnCompleted:
    def test_true(self):
        import json

        assert is_turn_completed(json.dumps({"type": "turn.completed"})) is True

    def test_false_other_type(self):
        import json

        assert is_turn_completed(json.dumps({"type": "message"})) is False

    def test_false_no_type(self):
        import json

        assert is_turn_completed(json.dumps({"data": "x"})) is False

    def test_invalid_json(self):
        assert is_turn_completed("not json") is False

    def test_empty_string(self):
        assert is_turn_completed("") is False

    def test_none_like(self):
        assert is_turn_completed("null") is False


class TestSanitizeExtraArgs:
    def test_none(self):
        assert sanitize_extra_args(None) is None

    def test_empty(self):
        result = sanitize_extra_args({})
        assert result is None or result == {}

    def test_normal_args(self):
        result = sanitize_extra_args({"model": "gpt-4o", "timeout": 60})
        assert result["model"] == "gpt-4o"
        assert result["timeout"] == 60

    def test_strips_flag_values(self):
        result = sanitize_extra_args({"model": "--malicious"})
        assert result is None or "model" not in result

    def test_strips_flags_in_list(self):
        result = sanitize_extra_args({"image": ["photo.png", "--exec=rm"]})
        assert "--exec=rm" not in result["image"]
        assert "photo.png" in result["image"]

    def test_mixed(self):
        result = sanitize_extra_args({
            "model": "safe",
            "bad": "--inject",
        })
        assert result["model"] == "safe"
        assert "bad" not in result


class TestBaseAdapter:
    def test_provider_name(self):
        a = BaseAdapter()
        assert a.provider_name == "unknown"

    def test_binary_name_raises(self):
        a = BaseAdapter()
        try:
            a._binary_name()
            assert False, "Should raise"
        except NotImplementedError:
            pass

    def test_build_command_raises(self):
        a = BaseAdapter()
        try:
            a.build_command("prompt", "/dir")
            assert False, "Should raise"
        except NotImplementedError:
            pass

    def test_parse_output_raises(self):
        a = BaseAdapter()
        try:
            a.parse_output([])
            assert False, "Should raise"
        except NotImplementedError:
            pass

    def test_parse_token_usage_default(self):
        a = BaseAdapter()
        assert a.parse_token_usage([]) is None


class _TestAdapter(BaseAdapter):
    """Concrete adapter for testing BaseAdapter.run()."""

    provider_name = "test"

    def __init__(self, available=True, build_error=False):
        self._available = available
        self._build_error = build_error

    def _binary_name(self):
        return "echo"

    def check_available(self):
        return self._available

    def build_command(self, prompt, workdir, sandbox="", session_id="", extra_args=None):
        if self._build_error:
            raise ValueError("bad command")
        return ["echo", prompt]

    def parse_output(self, lines):
        text = "\n".join(lines)
        return text, "sess-1", ""

    def parse_token_usage(self, lines):
        return TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)


class TestBaseAdapterRun:
    @pytest.mark.asyncio
    async def test_not_available(self):
        adapter = _TestAdapter(available=False)
        result = await adapter.run(prompt="hi", workdir="/tmp")
        assert result.status == "error"
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_build_command_error(self):
        adapter = _TestAdapter(build_error=True)
        result = await adapter.run(prompt="hi", workdir="/tmp")
        assert result.status == "error"
        assert "Failed to build command" in result.error

    @pytest.mark.asyncio
    async def test_file_not_found_error(self):
        adapter = _TestAdapter()

        def fake_stream(*a, **kw):
            raise FileNotFoundError("echo not found")
            yield  # make it a generator  # noqa: E501

        with patch("modelmux.adapters.base.stream_subprocess", fake_stream):
            result = await adapter.run(prompt="hi", workdir="/tmp")
        assert result.status == "error"
        assert "not found" in result.error
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        adapter = _TestAdapter()

        def fake_stream(*a, **kw):
            raise RuntimeError("boom")
            yield  # noqa: E501

        with patch("modelmux.adapters.base.stream_subprocess", fake_stream):
            result = await adapter.run(prompt="hi", workdir="/tmp")
        assert result.status == "error"
        assert "Subprocess error" in result.error

    @pytest.mark.asyncio
    async def test_timeout_exit_code(self):
        adapter = _TestAdapter()

        def fake_stream(*a, **kw):
            yield "partial output"
            return 124  # timeout

        with patch("modelmux.adapters.base.stream_subprocess", fake_stream):
            result = await adapter.run(prompt="hi", workdir="/tmp")
        assert result.status == "timeout"
        assert "Timed out" in result.error

    @pytest.mark.asyncio
    async def test_success(self):
        adapter = _TestAdapter()

        def fake_stream(*a, **kw):
            yield "hello world"
            return 0

        with patch("modelmux.adapters.base.stream_subprocess", fake_stream):
            result = await adapter.run(prompt="hi", workdir="/tmp")
        assert result.status == "success"
        assert result.output == "hello world"
        assert result.session_id == "sess-1"
        assert result.token_usage is not None
        assert result.token_usage.total_tokens == 15

    @pytest.mark.asyncio
    async def test_on_progress_callback(self):
        adapter = _TestAdapter()
        progress_msgs = []

        def fake_stream(*a, **kw):
            yield "line1"
            yield "line2"
            return 0

        with patch("modelmux.adapters.base.stream_subprocess", fake_stream):
            result = await adapter.run(
                prompt="hi", workdir="/tmp", on_progress=lambda m: progress_msgs.append(m)
            )
        assert result.status == "success"
        assert "Running test CLI..." in progress_msgs
        assert "line1" in progress_msgs
        assert "line2" in progress_msgs

    @pytest.mark.asyncio
    async def test_run_yields_to_event_loop_during_streaming(self):
        adapter = _TestAdapter()
        run_finished = False

        def fake_stream(*a, **kw):
            for idx in range(20):
                yield f"line{idx}"
            return 0

        async def do_run():
            nonlocal run_finished
            await adapter.run(prompt="hi", workdir="/tmp")
            run_finished = True

        async def observer():
            await asyncio.sleep(0)
            return run_finished

        with patch("modelmux.adapters.base.stream_subprocess", fake_stream):
            _, saw_finished = await asyncio.gather(do_run(), observer())

        assert saw_finished is False

    @pytest.mark.asyncio
    async def test_sanitizes_extra_args(self):
        adapter = _TestAdapter()

        def fake_stream(*a, **kw):
            yield "ok"
            return 0

        with patch("modelmux.adapters.base.stream_subprocess", fake_stream):
            result = await adapter.run(
                prompt="hi", workdir="/tmp", extra_args={"model": "--inject"}
            )
        assert result.status == "success"


class TestStreamSubprocess:
    def test_command_not_found(self):
        with pytest.raises(FileNotFoundError, match="Command not found"):
            gen = stream_subprocess(["nonexistent_binary_xyz_12345"])
            next(gen)

    def test_echo_command(self):
        lines = list(stream_subprocess(["echo", "hello"]))
        assert any("hello" in l for l in lines)

    def test_env_overrides(self):
        lines = list(
            stream_subprocess(
                ["env"],
                env_overrides={"MODELMUX_TEST_VAR": "test_value_123"},
            )
        )
        assert any("MODELMUX_TEST_VAR=test_value_123" in l for l in lines)
