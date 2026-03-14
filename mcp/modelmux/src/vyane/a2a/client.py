"""A2A Client — connect to external A2A agents.

Implements the client side of the Agent-to-Agent protocol:
  - Agent Card discovery (GET /.well-known/agent.json)
  - Synchronous task execution (tasks/send)
  - Task status query (tasks/get)
  - Task cancellation (tasks/cancel)
  - SSE streaming (tasks/sendSubscribe)
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("vyane.a2a.client")


@dataclass
class A2AClientConfig:
    """Configuration for an A2A client connection."""

    url: str = ""
    token: str = ""
    timeout: float = 600.0
    name: str = ""  # friendly name for this remote agent


@dataclass
class A2AResponse:
    """Parsed response from an A2A agent."""

    task_id: str = ""
    context_id: str = ""
    state: str = ""
    output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class A2AClient:
    """Client for connecting to external A2A agents."""

    def __init__(self, config: A2AClientConfig) -> None:
        self._config = config
        self._base_url = config.url.rstrip("/")
        self._headers: dict[str, str] = {}
        if config.token:
            self._headers["Authorization"] = f"Bearer {config.token}"

    @property
    def name(self) -> str:
        return self._config.name or self._base_url

    def _jsonrpc(
        self, method: str, params: dict[str, Any], req_id: int = 1
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

    def _build_task_params(
        self,
        task: str,
        pattern: str = "review",
        task_id: str = "",
        providers: dict[str, str] | None = None,
        timeout_per_turn: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": task}],
            },
        }
        metadata: dict[str, Any] = {"pattern": pattern}
        if providers:
            metadata["providers"] = providers
        if timeout_per_turn:
            metadata["timeout_per_turn"] = timeout_per_turn
        params["metadata"] = metadata
        if task_id:
            params["id"] = task_id
        return params

    async def discover(self) -> dict[str, Any]:
        """Fetch the Agent Card from the remote server."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/.well-known/agent.json",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def send(
        self,
        task: str,
        pattern: str = "review",
        task_id: str = "",
        providers: dict[str, str] | None = None,
        timeout_per_turn: int = 0,
    ) -> A2AResponse:
        """Send a task and wait for completion."""
        params = self._build_task_params(
            task, pattern, task_id, providers, timeout_per_turn
        )
        payload = self._jsonrpc("tasks/send", params)

        async with httpx.AsyncClient(timeout=self._config.timeout) as client:
            resp = await client.post(
                f"{self._base_url}/",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            body = resp.json()

        return self._parse_response(body)

    async def get(self, task_id: str) -> A2AResponse:
        """Query the status of a task."""
        payload = self._jsonrpc("tasks/get", {"id": task_id})

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            body = resp.json()

        return self._parse_response(body)

    async def cancel(self, task_id: str) -> A2AResponse:
        """Cancel a running task."""
        payload = self._jsonrpc("tasks/cancel", {"id": task_id})

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            body = resp.json()

        return self._parse_response(body)

    async def send_subscribe(
        self,
        task: str,
        pattern: str = "review",
        task_id: str = "",
        providers: dict[str, str] | None = None,
        timeout_per_turn: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Send a task and stream updates via SSE.

        Yields parsed SSE events as dicts with 'event' and 'data' keys.
        """
        params = self._build_task_params(
            task, pattern, task_id, providers, timeout_per_turn
        )
        payload = self._jsonrpc("tasks/sendSubscribe", params)

        async with httpx.AsyncClient(timeout=self._config.timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/",
                json=payload,
                headers=self._headers,
            ) as resp:
                resp.raise_for_status()
                current_event: dict[str, str] = {}
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event["event"] = line[6:].strip()
                    elif line.startswith("data:"):
                        try:
                            current_event["data"] = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            current_event["data"] = line[5:].strip()
                        yield current_event
                        current_event = {}

    async def check_available(self) -> bool:
        """Check if the remote A2A agent is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._base_url}/health",
                    headers=self._headers,
                )
                return resp.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    def _parse_response(self, body: dict[str, Any]) -> A2AResponse:
        """Parse a JSON-RPC response into A2AResponse."""
        if "error" in body:
            err = body["error"]
            return A2AResponse(
                error=err.get("message", str(err)),
                raw=body,
            )

        result = body.get("result", {})

        # Extract output from history (last agent message)
        output = ""
        history = result.get("history", [])
        for entry in reversed(history):
            if entry.get("role") == "agent":
                parts = entry.get("parts", [])
                for part in parts:
                    if part.get("type", "text") == "text":
                        output = part.get("text", "")
                        break
                if output:
                    break

        return A2AResponse(
            task_id=result.get("id", ""),
            context_id=result.get("contextId", ""),
            state=result.get("status", {}).get("state", ""),
            output=output,
            metadata=result.get("metadata", {}),
            history=history,
            artifacts=result.get("artifacts", []),
            raw=body,
        )
