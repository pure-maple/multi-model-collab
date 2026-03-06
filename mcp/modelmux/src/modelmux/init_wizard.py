"""Interactive setup wizard for modelmux configuration.

Run with: modelmux init
Generates profiles.toml and optionally policy.json.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# ANSI color helpers
_GREEN = "\033[0;32m"
_YELLOW = "\033[1;33m"
_CYAN = "\033[0;36m"
_BOLD = "\033[1m"
_NC = "\033[0m"

PROVIDERS = ["codex", "gemini", "claude", "ollama"]

PROVIDER_INFO = {
    "codex": {"binary": "codex", "desc": "Codex CLI (code, algorithms)"},
    "gemini": {"binary": "gemini", "desc": "Gemini CLI (frontend, design)"},
    "claude": {"binary": "claude", "desc": "Claude Code (architecture, reasoning)"},
    "ollama": {"binary": "ollama", "desc": "Ollama (DeepSeek, Llama, Qwen)"},
}


def _info(msg: str) -> None:
    print(f"{_GREEN}[+]{_NC} {msg}")


def _header(msg: str) -> None:
    print(f"\n{_BOLD}{_CYAN}{msg}{_NC}")


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    result = input(f"  {prompt}{suffix}: ").strip()
    return result or default


def _ask_yn(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    result = input(f"  {prompt}{suffix}: ").strip().lower()
    if not result:
        return default
    return result in ("y", "yes")


def _ask_choice(prompt: str, choices: list[str], default: str = "") -> str:
    for i, c in enumerate(choices, 1):
        print(f"    {i}. {c}")
    while True:
        result = _ask(prompt, default)
        if result in choices:
            return result
        try:
            idx = int(result)
            if 1 <= idx <= len(choices):
                return choices[idx - 1]
        except ValueError:
            pass
        print(f"  {_YELLOW}Please enter a valid choice.{_NC}")


def detect_clis() -> dict[str, bool]:
    """Detect which model CLIs are installed."""
    available = {}
    for name, info in PROVIDER_INFO.items():
        available[name] = shutil.which(info["binary"]) is not None
    return available


def run_wizard(scope: str = "user") -> None:
    """Run the interactive configuration wizard."""
    print(f"\n{_BOLD}{'=' * 50}{_NC}")
    print(f"{_BOLD}  modelmux — Configuration Wizard{_NC}")
    print(f"{_BOLD}{'=' * 50}{_NC}")

    # Step 1: Detect CLIs
    _header("Step 1: Detecting installed CLIs")
    available = detect_clis()
    installed = []
    for name, is_available in available.items():
        status = f"{_GREEN}found{_NC}" if is_available else f"{_YELLOW}not found{_NC}"
        desc = PROVIDER_INFO[name]["desc"]
        print(f"  {name:8s} {status:30s}  {desc}")
        if is_available:
            installed.append(name)

    if not installed:
        msg = "No model CLIs detected. Install at least one."
        print(f"\n  {_YELLOW}{msg}{_NC}")
        print("  You can still generate a config and install CLIs later.")
        installed = ["codex"]  # Default for config generation

    # Step 2: Default provider
    _header("Step 2: Choose default provider")
    print("  When provider='auto' has no keyword match, which model should be used?")
    default_provider = _ask_choice("Default provider", installed, installed[0])
    _info(f"Default provider: {default_provider}")

    # Step 3: Routing rules
    _header("Step 3: Custom routing rules (optional)")
    routing_rules = []
    if _ask_yn("Add custom keyword routing rules?", default=False):
        while True:
            provider = _ask_choice(
                "Route to which provider?",
                [p for p in installed if p != default_provider] or installed,
            )
            keywords_raw = _ask("Keywords (comma-separated)", "")
            if keywords_raw:
                keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
                routing_rules.append({"provider": provider, "keywords": keywords})
                _info(f"Rule: [{', '.join(keywords)}] → {provider}")

            if not _ask_yn("Add another rule?", default=False):
                break

    # Step 4: Policy
    _header("Step 4: Safety policy (optional)")
    policy_config = {}
    if _ask_yn("Configure rate limits and safety policy?", default=False):
        max_per_hour = _ask("Max calls per hour (0=unlimited)", "0")
        max_per_day = _ask("Max calls per day (0=unlimited)", "0")
        block_full = _ask_yn("Block 'full' sandbox level?", default=True)

        if int(max_per_hour) > 0:
            policy_config["max_calls_per_hour"] = int(max_per_hour)
        if int(max_per_day) > 0:
            policy_config["max_calls_per_day"] = int(max_per_day)
        if block_full:
            policy_config["blocked_sandboxes"] = ["full"]

    # Step 5: Scope
    _header("Step 5: Config location")
    if scope == "auto":
        scope = _ask_choice(
            "Where to save config?",
            ["user", "project"],
            "user",
        )

    if scope == "project":
        config_dir = Path.cwd() / ".modelmux"
    else:
        config_dir = Path.home() / ".config" / "modelmux"

    config_dir.mkdir(parents=True, exist_ok=True)

    # Generate TOML config
    _header("Generating configuration")
    toml_lines = _generate_toml(default_provider, routing_rules)
    config_path = config_dir / "profiles.toml"

    if config_path.exists():
        if not _ask_yn(f"  {config_path} already exists. Overwrite?", default=False):
            print("  Skipped profiles.toml (kept existing)")
        else:
            config_path.write_text(toml_lines, encoding="utf-8")
            _info(f"Saved: {config_path}")
    else:
        config_path.write_text(toml_lines, encoding="utf-8")
        _info(f"Saved: {config_path}")

    # Generate policy.json
    if policy_config:
        policy_path = config_dir / "policy.json"
        policy_path.write_text(
            json.dumps(policy_config, indent=2) + "\n",
            encoding="utf-8",
        )
        _info(f"Saved: {policy_path}")

    # Summary
    _header("Setup complete!")
    print(f"  Config directory: {config_dir}")
    print(f"  Default provider: {default_provider}")
    if routing_rules:
        print(f"  Custom routing rules: {len(routing_rules)}")
    if policy_config:
        print("  Policy configured: yes")
    print("\n  Test it with:")
    print('    mux_dispatch(provider="auto", task="hello world")')
    print("    mux_check()")
    print()


def _generate_toml(
    default_provider: str,
    routing_rules: list[dict],
) -> str:
    """Generate a TOML configuration string."""
    lines = [
        "# modelmux configuration",
        "# Generated by: modelmux init",
        "#",
        "# Docs: https://github.com/pure-maple/modelmux",
        "",
        "[routing]",
        f'default_provider = "{default_provider}"',
        "",
    ]

    for rule in routing_rules:
        lines.append("[[routing.rules]]")
        lines.append(f'provider = "{rule["provider"]}"')
        lines.append("[routing.rules.match]")
        kw_str = ", ".join(f'"{k}"' for k in rule["keywords"])
        lines.append(f"keywords = [{kw_str}]")
        lines.append("")

    lines.extend(
        [
            "# Caller detection",
            "auto_exclude_caller = true",
            '# caller_override = ""  # Force: "claude" / "codex" / "gemini"',
            "",
            "# Profiles for custom model/API configuration",
            "# [profiles.budget]",
            '# description = "Use cheaper models"',
            "# [profiles.budget.providers.codex]",
            '# model = "gpt-4.1-mini"',
            "# [profiles.budget.providers.ollama]",
            '# model = "deepseek-r1:1.5b"',
            "",
        ]
    )

    return "\n".join(lines) + "\n"
