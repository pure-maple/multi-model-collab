"""DashScope adapter for Alibaba Cloud Coding Plan models.

Supports qwen, kimi, glm, minimax models via OpenAI-compatible API.
Uses httpx for direct HTTP calls (no CLI subprocess).

Default base URL: https://coding.dashscope.aliyuncs.com/v1
API key env var: DASHSCOPE_CODING_API_KEY (sk-sp-xxx format)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable

import httpx

from modelmux.adapters.base import AdapterResult, BaseAdapter

DEFAULT_MODEL = "qwen3-coder-plus"
DEFAULT_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
DEFAULT_API_KEY_ENV = "DASHSCOPE_CODING_API_KEY"

# All models available in Coding Plan
CODING_PLAN_MODELS = {
    # Lite + Pro
    "qwen3.5-plus",
    "kimi-k2.5",
    "glm-5",
    "MiniMax-M2.5",
    # Lite only (more models)
    "qwen3-max-2026-01-23",
    "qwen3-coder-next",
    "qwen3-coder-plus",
    "glm-4.7",
}


class DashScopeAdapter(BaseAdapter):
    """Adapter for Alibaba Cloud DashScope Coding Plan models."""

    provider_name = "dashscope"

    def __init__(
        self,
        base_url: str = "",
        api_key_env: str = "",
        default_model: str = "",
    ) -> None:
        self._base_url = base_url or DEFAULT_BASE_URL
        self._api_key_env = api_key_env or DEFAULT_API_KEY_ENV
        self._default_model = default_model or DEFAULT_MODEL

    def _binary_name(self) -> str:
        return "dashscope-api"

    def _get_api_key(self) -> str:
        return os.environ.get(self._api_key_env, "")

    def check_available(self) -> bool:
        # Check env var; config-based key is validated at run time
        # via env_overrides from ProviderConfig
        if self._get_api_key():
            return True
        # Also check if user has dashscope config in profiles
        try:
            from modelmux.config import load_config

            config = load_config(".")
            for prof in config.profiles.values():
                pc = prof.providers.get("dashscope")
                if pc and pc.api_key_env:
                    val = os.environ.get(pc.api_key_env, "")
                    if val:
                        return True
        except Exception:
            pass
        return False

    def build_command(self, prompt, workdir, **kw):
        return []  # Not used — HTTP adapter

    def parse_output(self, lines):
        return "", "", ""  # Not used — HTTP adapter

    async def run(
        self,
        prompt: str = "",
        workdir: str = ".",
        sandbox: str = "read-only",
        session_id: str = "",
        timeout: int = 300,
        extra_args: dict | None = None,
        env_overrides: dict[str, str] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> AdapterResult:
        run_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        # API key: env_overrides (from config) > env var
        api_key = ""
        if env_overrides:
            api_key = env_overrides.get("DASHSCOPE_CODING_API_KEY", "")
        if not api_key:
            api_key = self._get_api_key()
        if not api_key:
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="error",
                error=(
                    f"API key not configured. Set {self._api_key_env} env var "
                    "or add dashscope provider config in profiles.toml"
                ),
            )

        model = self._default_model
        if extra_args and extra_args.get("model"):
            model = extra_args["model"]

        # Base URL: env_overrides (from config) > extra_args > default
        base_url = self._base_url
        if env_overrides and env_overrides.get("DASHSCOPE_BASE_URL"):
            base_url = env_overrides["DASHSCOPE_BASE_URL"]
        if extra_args and extra_args.get("base_url"):
            base_url = extra_args["base_url"]

        if on_progress:
            on_progress(f"Calling DashScope API ({model})...")

        messages = [{"role": "user", "content": prompt}]

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                    },
                )

                duration = time.monotonic() - start

                if resp.status_code != 200:
                    error_text = resp.text[:500]
                    return AdapterResult(
                        run_id=run_id,
                        provider=self.provider_name,
                        status="error",
                        error=f"HTTP {resp.status_code}: {error_text}",
                        duration_seconds=duration,
                    )

                data = resp.json()

        except httpx.TimeoutException:
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="timeout",
                error=f"Timed out after {timeout}s",
                duration_seconds=time.monotonic() - start,
            )
        except Exception as e:
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="error",
                error=f"HTTP request failed: {e}",
                duration_seconds=time.monotonic() - start,
            )

        # Parse OpenAI-compatible response
        try:
            choices = data.get("choices", [])
            if not choices:
                return AdapterResult(
                    run_id=run_id,
                    provider=self.provider_name,
                    status="error",
                    error=f"Empty response: {json.dumps(data)[:300]}",
                    duration_seconds=duration,
                )

            content = choices[0].get("message", {}).get("content", "")
            actual_model = data.get("model", model)

            if on_progress and content:
                for line in content.split("\n")[:5]:
                    on_progress(line)

            summary = content[:200].replace("\n", " ") if content else ""

            return AdapterResult(
                run_id=run_id,
                provider=f"dashscope/{actual_model}",
                status="success" if content else "error",
                summary=summary,
                output=content,
                session_id=session_id,
                duration_seconds=duration,
                error=None if content else "Empty content in response",
            )

        except (KeyError, IndexError, TypeError) as e:
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="error",
                error=f"Failed to parse response: {e}",
                duration_seconds=duration,
            )
