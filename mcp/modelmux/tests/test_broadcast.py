"""Tests for broadcast multi-model support and provider/model parsing."""

from vyane.server import _parse_provider_spec


class TestParseProviderSpec:
    def test_plain_provider(self):
        assert _parse_provider_spec("codex") == ("codex", "")

    def test_provider_with_model(self):
        assert _parse_provider_spec("dashscope/kimi-k2.5") == (
            "dashscope",
            "kimi-k2.5",
        )

    def test_provider_with_complex_model(self):
        assert _parse_provider_spec("dashscope/qwen3-max-2026-01-23") == (
            "dashscope",
            "qwen3-max-2026-01-23",
        )

    def test_codex_with_model(self):
        assert _parse_provider_spec("codex/gpt-4.1-mini") == ("codex", "gpt-4.1-mini")

    def test_auto_provider(self):
        assert _parse_provider_spec("auto") == ("auto", "")

    def test_ollama_with_model(self):
        assert _parse_provider_spec("ollama/deepseek-r1") == (
            "ollama",
            "deepseek-r1",
        )
