"""Model CLI adapters for modelmux."""

from modelmux.adapters.base import AdapterResult, BaseAdapter
from modelmux.adapters.claude import ClaudeAdapter
from modelmux.adapters.codex import CodexAdapter
from modelmux.adapters.gemini import GeminiAdapter
from modelmux.adapters.generic import GenericAdapter
from modelmux.adapters.ollama import OllamaAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
    "claude": ClaudeAdapter,
    "ollama": OllamaAdapter,
}

# Stores instantiated generic adapters (keyed by provider name)
_custom_adapters: dict[str, GenericAdapter] = {}


def register_custom_provider(
    name: str,
    command: str,
    args: list[str] | None = None,
    description: str = "",
) -> None:
    """Register a user-defined provider at runtime."""
    adapter = GenericAdapter(
        name=name,
        command=command,
        args_template=args,
        description=description,
    )
    _custom_adapters[name] = adapter


def get_all_adapters() -> dict[str, type[BaseAdapter] | GenericAdapter]:
    """Return all adapters including custom ones."""
    result: dict = dict(ADAPTERS)
    result.update(_custom_adapters)
    return result


def load_custom_providers(config_data: dict) -> None:
    """Load custom providers from parsed config data.

    Config format:
        [providers.my-tool]
        command = "my-cli"
        args = ["--prompt", "{task}"]
        description = "My custom tool"
    """
    providers_section = config_data.get("providers", {})
    if not isinstance(providers_section, dict):
        return

    for name, pdata in providers_section.items():
        if not isinstance(pdata, dict):
            continue
        # Skip built-in provider names
        if name in ADAPTERS:
            continue
        command = pdata.get("command", "")
        if not command:
            continue
        register_custom_provider(
            name=name,
            command=command,
            args=pdata.get("args"),
            description=pdata.get("description", ""),
        )


__all__ = [
    "BaseAdapter",
    "AdapterResult",
    "CodexAdapter",
    "GeminiAdapter",
    "ClaudeAdapter",
    "OllamaAdapter",
    "GenericAdapter",
    "ADAPTERS",
    "get_all_adapters",
    "register_custom_provider",
    "load_custom_providers",
]
