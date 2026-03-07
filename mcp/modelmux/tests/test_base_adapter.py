"""Tests for the base adapter module (AdapterResult, TokenUsage, utilities)."""

from modelmux.adapters.base import (
    AdapterResult,
    BaseAdapter,
    TokenUsage,
    is_turn_completed,
    sanitize_extra_args,
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
