"""Model CLI adapters for modelmux."""

from modelmux.adapters.a2a_remote import A2ARemoteAdapter
from modelmux.adapters.base import AdapterResult, BaseAdapter
from modelmux.adapters.claude import ClaudeAdapter
from modelmux.adapters.codex import CodexAdapter
from modelmux.adapters.dashscope import DashScopeAdapter
from modelmux.adapters.gemini import GeminiAdapter
from modelmux.adapters.generic import GenericAdapter
from modelmux.adapters.ollama import OllamaAdapter
from modelmux.adapters.opencode import OpencodeAdapter

ADAPTERS: dict[str, type[BaseAdapter] | BaseAdapter] = {
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
    "claude": ClaudeAdapter,
    "ollama": OllamaAdapter,
    "dashscope": DashScopeAdapter,
    "opencode": OpencodeAdapter,
}

# Stores instantiated generic/remote adapters (keyed by provider name)
_custom_adapters: dict[str, GenericAdapter | A2ARemoteAdapter] = {}


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


def register_a2a_agent(
    name: str,
    url: str,
    token: str = "",
    default_pattern: str = "review",
) -> None:
    """Register a remote A2A agent as a provider."""
    adapter = A2ARemoteAdapter(
        name=name,
        url=url,
        token=token,
        default_pattern=default_pattern,
    )
    _custom_adapters[name] = adapter


def get_all_adapters() -> dict[str, type[BaseAdapter] | BaseAdapter]:
    """Return all adapters including custom and remote ones."""
    result: dict = dict(ADAPTERS)
    result.update(_custom_adapters)
    return result


def load_custom_providers(config_data: dict) -> None:
    """Load custom providers and A2A agents from parsed config data.

    Config format (CLI providers):
        [providers.my-tool]
        command = "my-cli"
        args = ["--prompt", "{task}"]
        description = "My custom tool"

    Config format (A2A remote agents):
        [a2a_agents.remote1]
        url = "http://localhost:41520"
        token = "secret"
        pattern = "review"
    """
    # CLI providers
    providers_section = config_data.get("providers", {})
    if isinstance(providers_section, dict):
        for name, pdata in providers_section.items():
            if not isinstance(pdata, dict):
                continue
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

    # A2A remote agents
    agents_section = config_data.get("a2a_agents", {})
    if isinstance(agents_section, dict):
        for name, adata in agents_section.items():
            if not isinstance(adata, dict):
                continue
            url = adata.get("url", "")
            if not url:
                continue
            register_a2a_agent(
                name=name,
                url=url,
                token=adata.get("token", ""),
                default_pattern=adata.get("pattern", "review"),
            )


__all__ = [
    "BaseAdapter",
    "AdapterResult",
    "CodexAdapter",
    "GeminiAdapter",
    "ClaudeAdapter",
    "OllamaAdapter",
    "DashScopeAdapter",
    "GenericAdapter",
    "A2ARemoteAdapter",
    "OpencodeAdapter",
    "ADAPTERS",
    "get_all_adapters",
    "register_custom_provider",
    "register_a2a_agent",
    "load_custom_providers",
]
