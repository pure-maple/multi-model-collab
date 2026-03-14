"""A2A Remote Adapter — dispatch tasks to external A2A agents.

Wraps an A2AClient as a standard BaseAdapter, allowing remote A2A agents
to be used seamlessly via mux_dispatch(provider="my-remote-agent").
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from vyane.a2a.client import A2AClient, A2AClientConfig
from vyane.adapters.base import AdapterResult, BaseAdapter


class A2ARemoteAdapter(BaseAdapter):
    """Adapter that dispatches to an external A2A agent."""

    provider_name: str = "a2a-remote"

    def __init__(
        self,
        name: str,
        url: str,
        token: str = "",
        default_pattern: str = "review",
    ) -> None:
        self.provider_name = name
        self._url = url
        self._token = token
        self._default_pattern = default_pattern
        self._client = A2AClient(A2AClientConfig(url=url, token=token, name=name))

    def _binary_name(self) -> str:
        return f"a2a:{self._url}"

    def check_available(self) -> bool:
        # For remote agents, we assume available at registration time.
        # Actual availability is checked at runtime via health endpoint.
        return True

    def build_command(self, prompt, workdir, **kw):
        # Not used for A2A remote adapters
        return []

    def parse_output(self, lines):
        # Not used for A2A remote adapters
        return "", "", ""

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
        """Dispatch to remote A2A agent."""
        run_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        # Extract pattern from extra_args if provided
        pattern = self._default_pattern
        if extra_args:
            pattern = extra_args.get("pattern", pattern)

        if on_progress:
            on_progress(f"Dispatching to remote A2A agent: {self.provider_name}...")

        try:
            # Check if agent is reachable
            reachable = await self._client.check_available()
            if not reachable:
                return AdapterResult(
                    run_id=run_id,
                    provider=self.provider_name,
                    status="error",
                    error=f"Remote A2A agent unreachable: {self._url}",
                    duration_seconds=time.monotonic() - start,
                )

            # Update client timeout
            self._client._config.timeout = float(timeout)

            response = await self._client.send(
                task=prompt,
                pattern=pattern,
            )

            duration = time.monotonic() - start

            if response.error:
                return AdapterResult(
                    run_id=run_id,
                    provider=self.provider_name,
                    status="error",
                    error=response.error,
                    duration_seconds=duration,
                )

            status = "success" if response.state in ("completed",) else "error"

            output = response.output
            summary = output[:200].replace("\n", " ") if output else ""

            if on_progress and output:
                # Report final output
                for line in output.split("\n")[:5]:
                    on_progress(line)

            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status=status,
                summary=summary,
                output=output,
                session_id=response.context_id,
                duration_seconds=duration,
                error=(
                    f"Task ended in state: {response.state}"
                    if status == "error"
                    else None
                ),
            )

        except Exception as e:
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="error",
                error=f"A2A client error: {e}",
                duration_seconds=time.monotonic() - start,
            )
