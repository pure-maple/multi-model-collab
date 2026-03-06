"""Base adapter for CLI model bridges."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from threading import Thread
from typing import Generator

GRACEFUL_SHUTDOWN_DELAY = 0.3
QUEUE_READ_TIMEOUT = 0.5


@dataclass
class AdapterResult:
    """Canonical result schema for all model adapters."""

    run_id: str = ""
    provider: str = ""
    status: str = "error"  # success | error | timeout
    summary: str = ""
    output: str = ""
    session_id: str = ""
    duration_seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        d = {
            "run_id": self.run_id,
            "provider": self.provider,
            "status": self.status,
            "summary": self.summary,
            "output": self.output,
            "session_id": self.session_id,
            "duration_seconds": round(self.duration_seconds, 1),
        }
        if self.error:
            d["error"] = self.error
        return d


def is_turn_completed(line: str) -> bool:
    """Check if a JSONL line indicates turn completion."""
    try:
        data = json.loads(line)
        return data.get("type") == "turn.completed"
    except (json.JSONDecodeError, AttributeError, TypeError):
        return False


def stream_subprocess(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 300,
    env_overrides: dict[str, str] | None = None,
) -> Generator[str, None, int]:
    """Run a subprocess and yield stdout lines via a threaded queue.

    Returns the exit code via generator return value.
    Uses the battle-tested pattern from GuDaStudio's codexmcp/geminimcp.
    """
    resolved = shutil.which(cmd[0])
    if not resolved:
        raise FileNotFoundError(f"Command not found: {cmd[0]}")
    cmd[0] = resolved

    proc_env = None
    if env_overrides:
        proc_env = os.environ.copy()
        proc_env.update(env_overrides)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
        env=proc_env,
        encoding="utf-8",
        errors="replace",
    )

    output_queue: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in iter(process.stdout.readline, ""):
            stripped = line.strip()
            if stripped:
                output_queue.put(stripped)
                if is_turn_completed(stripped):
                    time.sleep(GRACEFUL_SHUTDOWN_DELAY)
                    process.terminate()
                    break
        process.stdout.close()
        output_queue.put(None)

    reader = Thread(target=read_output, daemon=True)
    reader.start()

    start_time = time.monotonic()
    while True:
        elapsed = time.monotonic() - start_time
        if elapsed > timeout:
            process.terminate()
            process.wait(timeout=5)
            return 124  # timeout exit code

        try:
            line = output_queue.get(timeout=QUEUE_READ_TIMEOUT)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue

        if line is None:
            break
        yield line

    process.wait(timeout=10)
    return process.returncode or 0


class BaseAdapter:
    """Base class for model CLI adapters."""

    provider_name: str = "unknown"

    def check_available(self) -> bool:
        """Check if the CLI binary is available on PATH."""
        return shutil.which(self._binary_name()) is not None

    def _binary_name(self) -> str:
        raise NotImplementedError

    def build_command(
        self,
        prompt: str,
        workdir: str,
        sandbox: str = "read-only",
        session_id: str = "",
        extra_args: dict | None = None,
    ) -> list[str]:
        raise NotImplementedError

    def parse_output(self, lines: list[str]) -> tuple[str, str, str]:
        """Parse collected output lines.

        Returns (agent_text, session_id, error_text).
        """
        raise NotImplementedError

    async def run(
        self,
        prompt: str,
        workdir: str,
        sandbox: str = "read-only",
        session_id: str = "",
        timeout: int = 300,
        extra_args: dict | None = None,
        env_overrides: dict[str, str] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> AdapterResult:
        """Execute a task and return the canonical result.

        Args:
            on_progress: Optional callback invoked with status messages
                during execution (e.g., for MCP progress notifications).
        """
        run_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        if not self.check_available():
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="error",
                error=f"{self._binary_name()} not found on PATH",
            )

        try:
            cmd = self.build_command(prompt, workdir, sandbox, session_id, extra_args)
        except Exception as e:
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="error",
                error=f"Failed to build command: {e}",
            )

        if on_progress:
            on_progress(f"Running {self.provider_name} CLI...")

        lines: list[str] = []
        exit_code = 0
        try:
            gen = stream_subprocess(
                cmd,
                cwd=workdir,
                timeout=timeout,
                env_overrides=env_overrides,
            )
            for line in gen:
                lines.append(line)
            # Get the return value (exit code) from the generator
            try:
                next(gen)
            except StopIteration as e:
                exit_code = e.value if e.value is not None else 0
        except FileNotFoundError as e:
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="error",
                error=str(e),
                duration_seconds=time.monotonic() - start,
            )
        except Exception as e:
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="error",
                error=f"Subprocess error: {e}",
                duration_seconds=time.monotonic() - start,
            )

        duration = time.monotonic() - start

        if exit_code == 124:
            return AdapterResult(
                run_id=run_id,
                provider=self.provider_name,
                status="timeout",
                output="\n".join(lines[-50:]),
                duration_seconds=duration,
                error=f"Timed out after {timeout}s",
            )

        agent_text, new_session_id, error_text = self.parse_output(lines)

        # Generate summary (first 200 chars of agent text)
        summary = agent_text[:200].replace("\n", " ") if agent_text else ""

        status = "success" if agent_text and not error_text else "error"

        return AdapterResult(
            run_id=run_id,
            provider=self.provider_name,
            status=status,
            summary=summary,
            output=agent_text or error_text or "\n".join(lines),
            session_id=new_session_id or session_id,
            duration_seconds=duration,
            error=error_text if error_text else None,
        )
