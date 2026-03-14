"""Generic adapter for user-defined CLI providers.

Allows users to register custom providers via config:

    [providers.deepseek]
    command = "deepseek-cli"
    args = ["--prompt", "{task}", "--workdir", "{workdir}"]
    description = "DeepSeek API CLI"
"""

from __future__ import annotations

from vyane.adapters.base import BaseAdapter


class GenericAdapter(BaseAdapter):
    """Adapter for user-defined CLI tools."""

    def __init__(
        self,
        name: str,
        command: str,
        args_template: list[str] | None = None,
        description: str = "",
    ):
        self.provider_name = name
        self._command = command
        self._args_template = args_template or ["{task}"]
        self._description = description

    def _binary_name(self) -> str:
        return self._command

    def build_command(
        self,
        prompt: str,
        workdir: str,
        sandbox: str = "read-only",
        session_id: str = "",
        extra_args: dict | None = None,
    ) -> list[str]:
        _RESERVED_KEYS = {"task", "workdir", "sandbox", "session_id"}
        substitutions = {
            "task": prompt,
            "workdir": workdir,
            "sandbox": sandbox,
            "session_id": session_id,
        }
        if extra_args:
            # Prevent extra_args from overriding built-in substitution keys
            safe = {k: str(v) for k, v in extra_args.items() if k not in _RESERVED_KEYS}
            substitutions.update(safe)

        args = []
        for arg in self._args_template:
            rendered = arg
            for key, val in substitutions.items():
                rendered = rendered.replace(f"{{{key}}}", val)
            args.append(rendered)

        return [self._command, *args]

    def parse_output(self, lines: list[str]) -> tuple[str, str, str]:
        """Plain text parsing — return all output as-is."""
        output = "\n".join(lines)
        return output, "", ""
