"""Tests for the DashScope adapter."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vyane.adapters.dashscope import (
    CODING_PLAN_MODELS,
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DashScopeAdapter,
)


class TestDashScopeAdapter:
    def test_provider_name(self):
        adapter = DashScopeAdapter()
        assert adapter.provider_name == "dashscope"

    def test_binary_name(self):
        adapter = DashScopeAdapter()
        assert adapter._binary_name() == "dashscope-api"

    def test_default_config(self):
        adapter = DashScopeAdapter()
        assert adapter._base_url == DEFAULT_BASE_URL
        assert adapter._api_key_env == DEFAULT_API_KEY_ENV
        assert adapter._default_model == DEFAULT_MODEL

    def test_custom_config(self):
        adapter = DashScopeAdapter(
            base_url="https://custom.api.com/v1",
            api_key_env="CUSTOM_KEY",
            default_model="kimi-k2.5",
        )
        assert adapter._base_url == "https://custom.api.com/v1"
        assert adapter._api_key_env == "CUSTOM_KEY"
        assert adapter._default_model == "kimi-k2.5"


class TestCheckAvailable:
    def test_available_with_env_key(self):
        adapter = DashScopeAdapter()
        with patch.dict("os.environ", {"DASHSCOPE_CODING_API_KEY": "sk-test"}):
            assert adapter.check_available() is True

    def test_not_available_without_key(self):
        adapter = DashScopeAdapter()
        with patch.dict("os.environ", {}, clear=True):
            with patch("vyane.config.load_config", side_effect=Exception):
                assert adapter.check_available() is False

    def test_available_with_custom_env(self):
        adapter = DashScopeAdapter(api_key_env="MY_CUSTOM_KEY")
        with patch.dict("os.environ", {"MY_CUSTOM_KEY": "sk-custom"}):
            assert adapter.check_available() is True


class TestRun:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_error(self):
        adapter = DashScopeAdapter()
        with patch.dict("os.environ", {}, clear=True):
            result = await adapter.run(prompt="hello")
        assert result.status == "error"
        assert "API key" in result.error

    @pytest.mark.asyncio
    async def test_successful_call(self):
        adapter = DashScopeAdapter()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": "Hello from DashScope"}}
            ],
            "model": "qwen3-coder-plus",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"DASHSCOPE_CODING_API_KEY": "sk-test"}):
            with patch("vyane.adapters.dashscope.httpx.AsyncClient", return_value=mock_client):
                result = await adapter.run(prompt="hello")

        assert result.status == "success"
        assert result.output == "Hello from DashScope"
        assert result.token_usage is not None
        assert result.token_usage.input_tokens == 10
        assert result.token_usage.output_tokens == 20
        assert "dashscope/" in result.provider

    @pytest.mark.asyncio
    async def test_http_error(self):
        adapter = DashScopeAdapter()

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"DASHSCOPE_CODING_API_KEY": "sk-test"}):
            with patch("vyane.adapters.dashscope.httpx.AsyncClient", return_value=mock_client):
                result = await adapter.run(prompt="hello")

        assert result.status == "error"
        assert "429" in result.error

    @pytest.mark.asyncio
    async def test_timeout(self):
        import httpx

        adapter = DashScopeAdapter()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"DASHSCOPE_CODING_API_KEY": "sk-test"}):
            with patch("vyane.adapters.dashscope.httpx.AsyncClient", return_value=mock_client):
                result = await adapter.run(prompt="hello", timeout=10)

        assert result.status == "timeout"
        assert "10s" in result.error

    @pytest.mark.asyncio
    async def test_empty_choices(self):
        adapter = DashScopeAdapter()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [], "model": "test"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"DASHSCOPE_CODING_API_KEY": "sk-test"}):
            with patch("vyane.adapters.dashscope.httpx.AsyncClient", return_value=mock_client):
                result = await adapter.run(prompt="hello")

        assert result.status == "error"
        assert "Empty response" in result.error

    @pytest.mark.asyncio
    async def test_model_override(self):
        adapter = DashScopeAdapter()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "model": "kimi-k2.5",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"DASHSCOPE_CODING_API_KEY": "sk-test"}):
            with patch("vyane.adapters.dashscope.httpx.AsyncClient", return_value=mock_client):
                result = await adapter.run(
                    prompt="hello",
                    extra_args={"model": "kimi-k2.5"},
                )

        # Verify the model was passed in the request
        call_args = mock_client.post.call_args
        body = call_args.kwargs["json"]
        assert body["model"] == "kimi-k2.5"

    @pytest.mark.asyncio
    async def test_env_overrides_api_key(self):
        adapter = DashScopeAdapter()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "model": "test",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # No env var set, but env_overrides provides the key
        with patch.dict("os.environ", {}, clear=True):
            with patch("vyane.adapters.dashscope.httpx.AsyncClient", return_value=mock_client):
                result = await adapter.run(
                    prompt="hello",
                    env_overrides={"DASHSCOPE_CODING_API_KEY": "sk-from-profile"},
                )

        assert result.status == "success"
        # Verify the key from env_overrides was used
        call_args = mock_client.post.call_args
        headers = call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-from-profile"

    @pytest.mark.asyncio
    async def test_on_progress_callback(self):
        adapter = DashScopeAdapter()
        progress_messages: list[str] = []

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "line1\nline2"}}],
            "model": "test",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"DASHSCOPE_CODING_API_KEY": "sk-test"}):
            with patch("vyane.adapters.dashscope.httpx.AsyncClient", return_value=mock_client):
                await adapter.run(
                    prompt="hello",
                    on_progress=lambda msg: progress_messages.append(msg),
                )

        # Should have "Calling..." message + content lines
        assert any("Calling DashScope" in m for m in progress_messages)


class TestCodingPlanModels:
    def test_known_models(self):
        assert "kimi-k2.5" in CODING_PLAN_MODELS
        assert "qwen3-coder-plus" in CODING_PLAN_MODELS
        assert "MiniMax-M2.5" in CODING_PLAN_MODELS

    def test_default_model_in_plan(self):
        assert DEFAULT_MODEL in CODING_PLAN_MODELS
