"""Unified MCP server for multi-model AI collaboration.

Exposes a single `collab_dispatch` tool that routes tasks to
Codex CLI, Gemini CLI, or Claude Code CLI, returning results
in a canonical schema.

Architecture: One hub, multiple internal adapters.
Consensus recommendation from Claude Opus 4.6, GPT-5.3-Codex,
and Gemini-3.1-Pro-Preview architecture consultation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from collab_hub.adapters import ADAPTERS, BaseAdapter

mcp = FastMCP(
    "collab-hub",
    instructions=(
        "Multi-model AI collaboration hub. Use collab_dispatch to send "
        "tasks to different AI models (codex, gemini, claude) and receive "
        "structured results. Supports session continuity for multi-turn "
        "conversations."
    ),
)

# Adapter instances (lazy-initialized)
_adapter_cache: dict[str, BaseAdapter] = {}


def _get_adapter(provider: str) -> BaseAdapter:
    if provider not in _adapter_cache:
        cls = ADAPTERS.get(provider)
        if cls is None:
            raise ValueError(
                f"Unknown provider: {provider}. "
                f"Available: {', '.join(ADAPTERS.keys())}"
            )
        _adapter_cache[provider] = cls()
    return _adapter_cache[provider]


@mcp.tool()
async def collab_dispatch(
    provider: Literal["codex", "gemini", "claude"],
    task: str,
    workdir: str = ".",
    sandbox: Literal["read-only", "write", "full"] = "read-only",
    session_id: str = "",
    timeout: int = 300,
    model: str = "",
) -> str:
    """Dispatch a task to an AI model CLI and return the result.

    Args:
        provider: Which model to use — "codex" (code generation, algorithms,
            debugging), "gemini" (frontend, design, multimodal), or "claude"
            (architecture, reasoning, review).
        task: The task description / prompt to send to the model.
        workdir: Working directory for the model to operate in.
        sandbox: Security level — "read-only" (default, safe), "write"
            (can modify files), "full" (unrestricted, dangerous).
        session_id: Resume a previous session for multi-turn conversation.
            Pass the session_id from a previous result to continue.
        timeout: Maximum seconds to wait (default 300).
        model: Override the specific model version (optional).
    """
    # Resolve workdir to absolute path
    resolved_workdir = str(Path(workdir).resolve())

    adapter = _get_adapter(provider)

    if not adapter.check_available():
        return json.dumps({
            "run_id": "",
            "provider": provider,
            "status": "error",
            "error": (
                f"{provider} CLI is not installed or not on PATH. "
                f"Please install it first."
            ),
        }, indent=2)

    extra_args: dict = {}
    if model:
        extra_args["model"] = model

    result = await adapter.run(
        prompt=task,
        workdir=resolved_workdir,
        sandbox=sandbox,
        session_id=session_id,
        timeout=timeout,
        extra_args=extra_args if extra_args else None,
    )

    return json.dumps(result.to_dict(), indent=2, ensure_ascii=False)


@mcp.tool()
async def collab_check() -> str:
    """Check which model CLIs are available on this system.

    Returns availability status for codex, gemini, and claude CLIs.
    Useful for determining which providers can be used with collab_dispatch.
    """
    status = {}
    for name, cls in ADAPTERS.items():
        adapter = cls()
        status[name] = {
            "available": adapter.check_available(),
            "binary": adapter._binary_name(),
        }
    return json.dumps(status, indent=2)
