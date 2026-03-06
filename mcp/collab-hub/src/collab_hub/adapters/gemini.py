"""Gemini CLI adapter.

Wraps `gemini --prompt ... -o stream-json` with JSON event parsing.
Session continuity via session_id → --resume.
"""

from __future__ import annotations

import json

from collab_hub.adapters.base import BaseAdapter

# Known Gemini CLI deprecation warnings to filter out
DEPRECATION_MARKERS = [
    "deprecated",
    "DeprecationWarning",
    "--prompt",
]


class GeminiAdapter(BaseAdapter):
    provider_name = "gemini"

    def _binary_name(self) -> str:
        return "gemini"

    def build_command(
        self,
        prompt: str,
        workdir: str,
        sandbox: str = "read-only",
        session_id: str = "",
        extra_args: dict | None = None,
    ) -> list[str]:
        cmd = ["gemini", "--prompt", prompt, "-o", "stream-json"]

        if sandbox in ("read-only", "sandbox"):
            cmd.append("--sandbox")

        if extra_args:
            if extra_args.get("model"):
                cmd.extend(["--model", extra_args["model"]])
            if extra_args.get("approval_mode"):
                cmd.extend(["--approval-mode", extra_args["approval_mode"]])

        if session_id:
            cmd.extend(["--resume", session_id])

        return cmd

    def parse_output(self, lines: list[str]) -> tuple[str, str, str]:
        """Parse Gemini stream-json events.

        Extracts assistant message content and session_id.
        """
        agent_messages: list[str] = []
        session_id = ""
        errors: list[str] = []

        for line in lines:
            # Skip known deprecation warnings
            if any(marker in line for marker in DEPRECATION_MARKERS):
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Extract session_id
            if data.get("session_id") and not session_id:
                session_id = data["session_id"]

            # Extract assistant messages
            msg_type = data.get("type", "")

            if msg_type == "message":
                role = data.get("role", "")
                content = data.get("content", "")
                if role == "assistant" and content:
                    agent_messages.append(content)

            # Also handle nested content format
            if msg_type == "content":
                parts = data.get("parts", [])
                for part in parts:
                    if isinstance(part, dict) and part.get("text"):
                        agent_messages.append(part["text"])
                    elif isinstance(part, str):
                        agent_messages.append(part)

            # Capture errors
            if msg_type in ("error", "fail"):
                err_msg = data.get("message", "") or data.get("error", "")
                if err_msg:
                    errors.append(err_msg)

        agent_text = "\n".join(agent_messages)
        error_text = "\n".join(errors)
        return agent_text, session_id, error_text
