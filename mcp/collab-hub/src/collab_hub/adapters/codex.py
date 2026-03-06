"""Codex CLI adapter.

Wraps `codex exec --json` with JSONL event parsing.
Session continuity via thread_id → resume.
"""

from __future__ import annotations

import json
import re

from collab_hub.adapters.base import BaseAdapter

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
