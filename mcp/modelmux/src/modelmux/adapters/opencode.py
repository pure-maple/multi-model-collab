"""opencode CLI adapter.

Wraps `opencode -p` (headless/non-interactive mode).
opencode supports 75+ providers via its config, making it a
universal fallback and long-tail provider access layer.

opencode outputs plain text, similar to Claude adapter.
Provider/model selection is passed via CLI flags or delegated
to opencode's own config (~/.config/opencode/config.json).
"""

from __future__ import annotations

from modelmux.adapters.base import BaseAdapter


class OpencodeAdapter(BaseAdapter):
    provider_name = "opencode"

    def _binary_name(self) -> str:
        return "opencode"

    def build_command(
        self,
        prompt: str,
        workdir: str,
        sandbox: str = "read-only",
        session_id: str = "",
        extra_args: dict | None = None,
    ) -> list[str]:
        cmd = ["opencode", "-p", prompt]

        if extra_args:
            if extra_args.get("model"):
                cmd.extend(["--model", extra_args["model"]])
            if extra_args.get("provider"):
                cmd.extend(["--provider", extra_args["provider"]])

        if session_id:
            cmd.extend(["--resume", session_id])

        return cmd

    def parse_output(self, lines: list[str]) -> tuple[str, str, str]:
        """Parse opencode plain text output.

        opencode in headless mode returns plain text.
        Session ID is extracted from a session line if present.
        """
        output_lines: list[str] = []
        session_id = ""

        for line in lines:
            # opencode may output a session line
            if line.startswith("Session:") or line.startswith("session:"):
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[1].strip():
                    session_id = parts[1].strip()
                continue

            output_lines.append(line)

        agent_text = "\n".join(output_lines)
        return agent_text, session_id, ""
