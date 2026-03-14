"""Ollama adapter for local model inference.

Wraps `ollama run <model> "<prompt>"` for any locally installed model
(DeepSeek, Llama, Qwen, Mistral, etc.).
No session support — each call is single-turn.
"""

from __future__ import annotations

from vyane.adapters.base import BaseAdapter

DEFAULT_MODEL = "llama3.2"


class OllamaAdapter(BaseAdapter):
    provider_name = "ollama"

    def _binary_name(self) -> str:
        return "ollama"

    def build_command(
        self,
        prompt: str,
        workdir: str,
        sandbox: str = "read-only",
        session_id: str = "",
        extra_args: dict | None = None,
    ) -> list[str]:
        model = DEFAULT_MODEL
        if extra_args and extra_args.get("model"):
            model = extra_args["model"]

        cmd = ["ollama", "run", model, prompt]

        return cmd

    def parse_output(self, lines: list[str]) -> tuple[str, str, str]:
        """Parse Ollama plain text output.

        Ollama outputs plain text to stdout. No session support.
        """
        output_lines: list[str] = []

        for line in lines:
            # Skip spinner/progress lines (model download progress)
            if line.startswith("pulling ") or line.startswith("verifying "):
                continue
            if "%" in line and ("B/" in line or "MB" in line):
                continue
            output_lines.append(line)

        agent_text = "\n".join(output_lines)
        return agent_text, "", ""
