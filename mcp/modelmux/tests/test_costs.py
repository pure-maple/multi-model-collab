"""Tests for cost tracking: token usage parsing + cost estimation."""

import json

from vyane.adapters.base import TokenUsage
from vyane.adapters.codex import CodexAdapter
from vyane.adapters.gemini import GeminiAdapter
from vyane.adapters.ollama import OllamaAdapter
from vyane.costs import CostEstimate, aggregate_costs, estimate_cost

# ── TokenUsage dataclass ──


class TestTokenUsage:
    def test_to_dict(self):
        u = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)
        d = u.to_dict()
        assert d == {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }

    def test_defaults(self):
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0
        assert u.total_tokens == 0


# ── CodexAdapter.parse_token_usage ──


class TestCodexTokenUsage:
    def test_extracts_from_turn_completed(self):
        adapter = CodexAdapter()
        lines = [
            json.dumps({"type": "message.created", "id": "msg1"}),
            json.dumps({"type": "response.text", "text": "hello"}),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 1200,
                        "output_tokens": 340,
                        "total_tokens": 1540,
                    },
                }
            ),
        ]
        usage = adapter.parse_token_usage(lines)
        assert usage is not None
        assert usage.input_tokens == 1200
        assert usage.output_tokens == 340
        assert usage.total_tokens == 1540

    def test_computes_total_if_missing(self):
        adapter = CodexAdapter()
        lines = [
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 500,
                        "output_tokens": 200,
                    },
                }
            ),
        ]
        usage = adapter.parse_token_usage(lines)
        assert usage is not None
        assert usage.total_tokens == 700

    def test_returns_none_without_usage(self):
        adapter = CodexAdapter()
        lines = [
            json.dumps({"type": "turn.completed"}),
        ]
        assert adapter.parse_token_usage(lines) is None

    def test_returns_none_for_non_jsonl(self):
        adapter = CodexAdapter()
        lines = ["plain text output", "more text"]
        assert adapter.parse_token_usage(lines) is None

    def test_uses_last_turn_completed(self):
        adapter = CodexAdapter()
        lines = [
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 800, "output_tokens": 200},
                }
            ),
        ]
        usage = adapter.parse_token_usage(lines)
        assert usage is not None
        # Should pick the last one (reversed iteration)
        assert usage.input_tokens == 800


# ── GeminiAdapter.parse_token_usage ──


class TestGeminiTokenUsage:
    def test_extracts_from_usage_metadata(self):
        adapter = GeminiAdapter()
        lines = [
            json.dumps({"text": "hello world"}),
            json.dumps(
                {
                    "usageMetadata": {
                        "promptTokenCount": 450,
                        "candidatesTokenCount": 120,
                        "totalTokenCount": 570,
                    }
                }
            ),
        ]
        usage = adapter.parse_token_usage(lines)
        assert usage is not None
        assert usage.input_tokens == 450
        assert usage.output_tokens == 120
        assert usage.total_tokens == 570

    def test_computes_total_if_missing(self):
        adapter = GeminiAdapter()
        lines = [
            json.dumps(
                {
                    "usageMetadata": {
                        "promptTokenCount": 300,
                        "candidatesTokenCount": 100,
                    }
                }
            ),
        ]
        usage = adapter.parse_token_usage(lines)
        assert usage is not None
        assert usage.total_tokens == 400

    def test_returns_none_without_metadata(self):
        adapter = GeminiAdapter()
        lines = [json.dumps({"text": "just text"})]
        assert adapter.parse_token_usage(lines) is None


# ── OllamaAdapter — no token usage ──


class TestOllamaTokenUsage:
    def test_returns_none(self):
        adapter = OllamaAdapter()
        lines = ["Hello from Ollama!", "More text."]
        assert adapter.parse_token_usage(lines) is None


# ── Cost estimation ──


class TestEstimateCost:
    def test_codex_default_pricing(self):
        est = estimate_cost("codex", 1_000_000, 1_000_000)
        assert est.input_cost == 2.0
        assert est.output_cost == 8.0
        assert est.total_cost == 10.0

    def test_specific_model(self):
        est = estimate_cost("codex", 1_000_000, 1_000_000, model="gpt-4.1-mini")
        assert est.input_cost == 0.4
        assert est.output_cost == 1.6

    def test_ollama_free(self):
        est = estimate_cost("ollama", 5000, 3000)
        assert est.total_cost == 0.0

    def test_unknown_provider(self):
        est = estimate_cost("unknown_provider", 1000, 500)
        assert est.total_cost == 0.0
        assert "No pricing data" in est.note

    def test_small_token_count(self):
        est = estimate_cost("codex", 1000, 500)
        assert est.total_cost > 0
        assert est.total_cost < 0.01

    def test_to_dict(self):
        est = CostEstimate(
            input_cost=0.002, output_cost=0.008, total_cost=0.01, model="gpt-4.1"
        )
        d = est.to_dict()
        assert d["total_cost"] == 0.01
        assert d["model"] == "gpt-4.1"
        assert d["currency"] == "USD"


# ── Cost aggregation ──


class TestAggregateCosts:
    def test_basic_aggregation(self):
        entries = [
            {
                "provider": "codex",
                "token_usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                },
            },
            {
                "provider": "codex",
                "token_usage": {
                    "input_tokens": 2000,
                    "output_tokens": 800,
                },
            },
            {
                "provider": "gemini",
                "token_usage": {
                    "input_tokens": 500,
                    "output_tokens": 200,
                },
            },
        ]
        result = aggregate_costs(entries)
        assert result["entries_with_usage"] == 3
        assert result["total_input_tokens"] == 3500
        assert result["total_output_tokens"] == 1500
        assert result["total_cost_usd"] > 0
        assert "codex" in result["by_provider"]
        assert "gemini" in result["by_provider"]
        assert result["by_provider"]["codex"]["calls"] == 2

    def test_skips_entries_without_usage(self):
        entries = [
            {"provider": "claude", "status": "success"},
            {
                "provider": "codex",
                "token_usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                },
            },
        ]
        result = aggregate_costs(entries)
        assert result["entries_with_usage"] == 1

    def test_empty_list(self):
        result = aggregate_costs([])
        assert result["entries_with_usage"] == 0
        assert result["total_cost_usd"] == 0.0


# ── AdapterResult includes token_usage ──


class TestAdapterResultTokenUsage:
    def test_to_dict_with_token_usage(self):
        from vyane.adapters.base import AdapterResult

        result = AdapterResult(
            run_id="abc",
            provider="codex",
            status="success",
            summary="test",
            output="output",
            token_usage=TokenUsage(
                input_tokens=1000, output_tokens=500, total_tokens=1500
            ),
        )
        d = result.to_dict()
        assert "token_usage" in d
        assert d["token_usage"]["input_tokens"] == 1000

    def test_to_dict_without_token_usage(self):
        from vyane.adapters.base import AdapterResult

        result = AdapterResult(
            run_id="abc",
            provider="claude",
            status="success",
        )
        d = result.to_dict()
        assert "token_usage" not in d


# ── DashScope token usage + cost estimation ──


class TestDashScopeTokenUsage:
    def test_extracts_usage_from_response(self):
        """DashScope adapter should extract token usage from OpenAI-compatible response."""
        import asyncio

        import httpx

        from vyane.adapters.dashscope import DashScopeAdapter

        adapter = DashScopeAdapter()

        # Mock the httpx response
        mock_response_data = {
            "id": "chatcmpl-test",
            "model": "qwen3-coder-plus",
            "choices": [
                {"message": {"role": "assistant", "content": "Hello!"}, "index": 0}
            ],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 15,
                "total_tokens": 57,
            },
        }

        async def mock_run():
            # Patch httpx to return mock data
            original_post = httpx.AsyncClient.post

            async def fake_post(self, url, **kwargs):
                resp = httpx.Response(
                    200,
                    json=mock_response_data,
                    request=httpx.Request("POST", url),
                )
                return resp

            httpx.AsyncClient.post = fake_post
            try:
                result = await adapter.run(
                    prompt="test",
                    env_overrides={"DASHSCOPE_CODING_API_KEY": "sk-sp-fake"},
                )
                return result
            finally:
                httpx.AsyncClient.post = original_post

        result = asyncio.run(mock_run())
        assert result.status == "success"
        assert result.token_usage is not None
        assert result.token_usage.input_tokens == 42
        assert result.token_usage.output_tokens == 15
        assert result.token_usage.total_tokens == 57

    def test_no_usage_in_response(self):
        """When API response has no usage field, token_usage should be None."""
        import asyncio

        import httpx

        from vyane.adapters.dashscope import DashScopeAdapter

        adapter = DashScopeAdapter()

        mock_response_data = {
            "model": "qwen3-coder-plus",
            "choices": [
                {"message": {"role": "assistant", "content": "Hi"}, "index": 0}
            ],
        }

        async def mock_run():
            original_post = httpx.AsyncClient.post

            async def fake_post(self, url, **kwargs):
                return httpx.Response(
                    200,
                    json=mock_response_data,
                    request=httpx.Request("POST", url),
                )

            httpx.AsyncClient.post = fake_post
            try:
                return await adapter.run(
                    prompt="test",
                    env_overrides={"DASHSCOPE_CODING_API_KEY": "sk-sp-fake"},
                )
            finally:
                httpx.AsyncClient.post = original_post

        result = asyncio.run(mock_run())
        assert result.status == "success"
        assert result.token_usage is None


class TestDashScopeCostEstimation:
    def test_dashscope_free_pricing(self):
        est = estimate_cost("dashscope", 100000, 50000)
        assert est.total_cost == 0.0

    def test_dashscope_specific_model(self):
        est = estimate_cost("dashscope", 100000, 50000, model="kimi-k2.5")
        assert est.total_cost == 0.0

    def test_provider_slash_model_format(self):
        """estimate_cost should handle 'provider/model' format."""
        est = estimate_cost("dashscope/qwen3-coder-plus", 1_000_000, 1_000_000)
        assert est.total_cost == 0.0
        assert est.model == "qwen3-coder-plus"

    def test_provider_slash_model_with_explicit_model(self):
        """Explicit model param takes precedence over embedded model."""
        est = estimate_cost(
            "codex/gpt-4.1", 1_000_000, 1_000_000, model="gpt-4.1-mini"
        )
        # Should use gpt-4.1-mini pricing, not gpt-4.1
        assert est.input_cost == 0.4

    def test_aggregate_with_dashscope_entries(self):
        entries = [
            {
                "provider": "dashscope/qwen3-coder-plus",
                "token_usage": {
                    "input_tokens": 5000,
                    "output_tokens": 2000,
                },
            },
            {
                "provider": "dashscope/kimi-k2.5",
                "token_usage": {
                    "input_tokens": 3000,
                    "output_tokens": 1000,
                },
            },
        ]
        result = aggregate_costs(entries)
        assert result["entries_with_usage"] == 2
        assert result["total_input_tokens"] == 8000
        assert result["total_output_tokens"] == 3000
        assert result["total_cost_usd"] == 0.0
