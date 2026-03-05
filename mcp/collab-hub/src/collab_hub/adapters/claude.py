"""Claude Code CLI adapter.

Wraps `claude -p` (print/non-interactive mode).
Claude outputs plain text, no structured JSON events.
"""

from __future__ import annotations

from collab_hub.adapters.base import BaseAdapter


class ClaudeAdapter(BaseAdapter):
    provider_name = "claude"

    def _binary_name(self) -> str:
        return "claude"

    def build_command(self, prompt: str, workdir: str,
                      sandbox: str = "read-only",
                      session_id: str = "",
                      extra_args: dict | None = None) -> list[str]:
        cmd = ["claude", "-p", prompt]

        if extra_args:
            if extra_args.get("model"):
                cmd.extend(["--model", extra_args["model"]])
            if extra_args.get("allowed_tools"):
                for tool in extra_args["allowed_tools"]:
                    cmd.extend(["--allowedTools", tool])

        if session_id:
            cmd.extend(["--resume", session_id])

        return cmd

    def parse_output(self, lines: list[str]) -> tuple[str, str, str]:
        """Parse Claude plain text output.

        Claude -p returns plain text, no JSON structure.
        Session ID is extracted from the session resume message if present.
        """
        output_lines: list[str] = []
        session_id = ""

        for line in lines:
            # Claude may output a session line at the start
            if line.startswith("Session:") or line.startswith("session:"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    session_id = parts[1].strip()
                continue

            output_lines.append(line)

        agent_text = "\n".join(output_lines)
        return agent_text, session_id, ""
