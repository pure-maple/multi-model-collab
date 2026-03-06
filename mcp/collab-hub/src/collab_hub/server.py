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
import re
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from collab_hub.adapters import ADAPTERS, BaseAdapter

mcp = FastMCP(
    "collab-hub",
    instructions=(
        "Multi-model AI collaboration hub. Use collab_dispatch to send "
        "tasks to different AI models (codex, gemini, claude) and receive "
        "structured results. Use provider='auto' for smart routing. "
        "Supports session continuity for multi-turn conversations."
    ),
)

# Adapter instances (lazy-initialized)
_adapter_cache: dict[str, BaseAdapter] = {}

# Auto-routing keyword patterns
_ROUTE_PATTERNS: dict[str, list[re.Pattern]] = {
    "gemini": [
        re.compile(r"\b(frontend|ui|ux|css|html|react|vue|svelte|angular|tailwind|"
                   r"component|layout|responsive|style|theme|dashboard|"
                   r"page|widget|modal|button|form|animation|figma|"
                   r"visual|color|font|icon|image|illustration)\b", re.I),
    ],
    "codex": [
        re.compile(r"\b(implement|algorithm|backend|api|endpoint|database|sql|"
                   r"debug|fix|bug|optimize|refactor|function|class|test|"
                   r"server|middleware|auth|crud|migration|schema|query|"
                   r"sort|search|tree|graph|linked.?list|hash|cache)\b", re.I),
    ],
    "claude": [
        re.compile(r"\b(architect|design.?pattern|review|analyze|explain|"
                   r"trade.?off|compare|evaluate|plan|strategy|"
                   r"security|audit|vulnerabilit|threat|"
                   r"documentation|spec|rfc|adr|critique)\b", re.I),
    ],
}


def _auto_route(task: str) -> str:
    """Pick the best provider based on task keywords.

    Returns the provider with the most keyword matches.
    Falls back to 'codex' as the most general-purpose option.
    """
    scores: dict[str, int] = {}
    for provider, patterns in _ROUTE_PATTERNS.items():
        score = sum(len(p.findall(task)) for p in patterns)
        scores[provider] = score

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        # No keyword matches — default to codex (most general)
        return "codex"
    return best


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
    provider: Literal["auto", "codex", "gemini", "claude"],
    task: str,
    workdir: str = ".",
    sandbox: Literal["read-only", "write", "full"] = "read-only",
    session_id: str = "",
    timeout: int = 300,
    model: str = "",
    profile: str = "",
    reasoning_effort: str = "",
) -> str:
    """Dispatch a task to an AI model CLI and return the result.

    Args:
        provider: Which model to use — "auto" (smart routing based on task),
            "codex" (code generation, algorithms, debugging), "gemini"
            (frontend, design, multimodal), or "claude" (architecture,
            reasoning, review).
        task: The task description / prompt to send to the model.
        workdir: Working directory for the model to operate in.
        sandbox: Security level — "read-only" (default, safe), "write"
            (can modify files), "full" (unrestricted, dangerous).
        session_id: Resume a previous session for multi-turn conversation.
            Pass the session_id from a previous result to continue.
        timeout: Maximum seconds to wait (default 300).
        model: Override the specific model version (e.g., "gpt-5.4",
            "gemini-2.5-pro", "claude-sonnet-4-6"). If empty, uses
            the CLI's default model from its own config.
        profile: Codex config profile name from ~/.codex/config.toml
            (e.g., "fast", "deep"). Only applies to provider="codex".
        reasoning_effort: Codex reasoning effort level — "low", "medium",
            "high", "xhigh". Only applies to provider="codex".
    """
    # Auto-route if needed
    actual_provider = provider
    if provider == "auto":
        actual_provider = _auto_route(task)

    # Resolve workdir to absolute path
    resolved_workdir = str(Path(workdir).resolve())

    adapter = _get_adapter(actual_provider)

    if not adapter.check_available():
        # If auto-routed provider unavailable, try fallback
        if provider == "auto":
            for fallback in ["codex", "gemini", "claude"]:
                if fallback != actual_provider:
                    fb_adapter = _get_adapter(fallback)
                    if fb_adapter.check_available():
                        actual_provider = fallback
                        adapter = fb_adapter
                        break
            else:
                return json.dumps({
                    "run_id": "",
                    "provider": actual_provider,
                    "status": "error",
                    "error": "No model CLIs available on PATH.",
                }, indent=2)
        else:
            return json.dumps({
                "run_id": "",
                "provider": actual_provider,
                "status": "error",
                "error": (
                    f"{actual_provider} CLI is not installed or not on PATH. "
                    f"Please install it first."
                ),
            }, indent=2)

    extra_args: dict = {}
    if model:
        extra_args["model"] = model
    if profile:
        extra_args["profile"] = profile
    if reasoning_effort:
        extra_args["reasoning_effort"] = reasoning_effort

    result = await adapter.run(
        prompt=task,
        workdir=resolved_workdir,
        sandbox=sandbox,
        session_id=session_id,
        timeout=timeout,
        extra_args=extra_args if extra_args else None,
    )

    result_dict = result.to_dict()
    if provider == "auto":
        result_dict["routed_from"] = "auto"
    return json.dumps(result_dict, indent=2, ensure_ascii=False)


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
