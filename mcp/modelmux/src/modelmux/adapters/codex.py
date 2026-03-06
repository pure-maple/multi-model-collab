"""Codex CLI adapter.

Wraps `codex exec --json` with JSONL event parsing.
Session continuity via thread_id → resume.

Includes workaround for Codex CLI UTF-8 header bug:
when workdir contains non-ASCII characters (e.g. Chinese path
like '我的云端硬盘'), the x-codex-turn-metadata HTTP header
encoding fails. We create a temporary ASCII symlink as a fix.
"""

from __future__ import annotations

import json
import os
import re
import tempfile

from modelmux.adapters.base import BaseAdapter


def _needs_ascii_workaround(path: str) -> bool:
    """Check if a path contains non-ASCII characters."""
    try:
        path.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def _create_ascii_symlink(target: str) -> str:
    """Create a temporary symlink with an ASCII-safe path.

    Returns the symlink path. Caller should clean up after use.
    """
    link_dir = tempfile.mkdtemp(prefix="mux-codex-")
    link_path = os.path.join(link_dir, "workdir")
    os.symlink(target, link_path)
    return link_path


# Regex to filter out reconnection noise
RECONNECT_RE = re.compile(r"^Reconnecting\.\.\.\s+\d+/\d+")


class CodexAdapter(BaseAdapter):
    provider_name = "codex"

    def _binary_name(self) -> str:
        return "codex"

    def build_command(
        self,
        prompt: str,
        workdir: str,
        sandbox: str = "read-only",
        session_id: str = "",
        extra_args: dict | None = None,
    ) -> list[str]:
        cmd = [
            "codex",
            "exec",
            "--json",
            "--cd",
            workdir,
            "--skip-git-repo-check",
        ]

        # Map sandbox levels
        sandbox_map = {
            "read-only": "read-only",
            "write": "workspace-write",
            "full": "danger-full-access",
        }
        codex_sandbox = sandbox_map.get(sandbox, sandbox)
        cmd.extend(["--sandbox", codex_sandbox])

        if extra_args:
            if extra_args.get("model"):
                cmd.extend(["--model", extra_args["model"]])
            if extra_args.get("profile"):
                cmd.extend(["--profile", extra_args["profile"]])
            if extra_args.get("reasoning_effort"):
                cmd.extend(["--reasoning-effort", extra_args["reasoning_effort"]])
            if extra_args.get("image"):
                for img in extra_args["image"]:
                    cmd.extend(["--image", str(img)])

        if session_id:
            cmd.extend(["resume", session_id])

        cmd.extend(["--", prompt])
        return cmd

    def parse_output(self, lines: list[str]) -> tuple[str, str, str]:
        """Parse Codex JSONL events.

        Extracts agent_message text and thread_id for session continuity.
        """
        agent_messages: list[str] = []
        thread_id = ""
        errors: list[str] = []

        for line in lines:
            # Skip reconnection messages
            if RECONNECT_RE.match(line):
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON line, could be CLI banner or warning
                continue

            # Extract thread_id for session continuity
            if data.get("thread_id") and not thread_id:
                thread_id = data["thread_id"]

            # Extract agent messages
            item = data.get("item", {})
            item_type = item.get("type", "")

            if item_type == "agent_message":
                text = item.get("text", "")
                if text:
                    agent_messages.append(text)

            # Capture errors
            if data.get("type") in ("error", "fail"):
                err_msg = data.get("message", "") or data.get("error", "")
                if err_msg:
                    errors.append(err_msg)

        agent_text = "\n".join(agent_messages)
        error_text = "\n".join(errors)
        return agent_text, thread_id, error_text

    async def run(
        self,
        prompt: str = "",
        workdir: str = ".",
        sandbox: str = "read-only",
        session_id: str = "",
        timeout: int = 300,
        extra_args: dict | None = None,
        env_overrides: dict[str, str] | None = None,
        on_progress=None,
    ):
        """Execute with ASCII workdir workaround for Codex UTF-8 bug."""
        ascii_link = ""
        actual_workdir = workdir

        if _needs_ascii_workaround(workdir):
            ascii_link = _create_ascii_symlink(workdir)
            actual_workdir = ascii_link

        try:
            return await super().run(
                prompt=prompt,
                workdir=actual_workdir,
                sandbox=sandbox,
                session_id=session_id,
                timeout=timeout,
                extra_args=extra_args,
                env_overrides=env_overrides,
                on_progress=on_progress,
            )
        finally:
            if ascii_link:
                try:
                    os.unlink(ascii_link)
                    os.rmdir(os.path.dirname(ascii_link))
                except OSError:
                    pass
