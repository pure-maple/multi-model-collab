"""Model CLI adapters for collab-hub."""

from collab_hub.adapters.base import BaseAdapter, AdapterResult
from collab_hub.adapters.codex import CodexAdapter
from collab_hub.adapters.gemini import GeminiAdapter
from collab_hub.adapters.claude import ClaudeAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
    "claude": ClaudeAdapter,
}

__all__ = [
    "BaseAdapter",
    "AdapterResult",
    "CodexAdapter",
    "GeminiAdapter",
    "ClaudeAdapter",
    "ADAPTERS",
]
