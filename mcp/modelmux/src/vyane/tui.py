"""TUI configuration panel for vyane.

Launch with: vyane config [--scope user|project]
Requires: pip install vyane[tui]  (or uvx --with textual vyane config)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from vyane.init_wizard import PROVIDER_INFO
from vyane.paths import user_config_dir

PROVIDERS = ["codex", "gemini", "claude", "ollama", "dashscope"]


def _load_raw(path: Path) -> dict:
    """Load raw config dict from a TOML/JSON/YAML file."""
    if not path.exists():
        return {}
    from vyane.config import _load_file

    try:
        return _load_file(path)
    except Exception:
        return {}


def _generate_toml(data: dict) -> str:
    """Generate TOML configuration string from a config dict."""
    lines = [
        "# vyane configuration",
        "# Edited by: vyane config",
        "",
    ]

    if data.get("auto_exclude_caller") is not None:
        val = "true" if data["auto_exclude_caller"] else "false"
        lines.append(f"auto_exclude_caller = {val}")

    if data.get("caller_override"):
        lines.append(f'caller_override = "{data["caller_override"]}"')

    if data.get("disabled_providers"):
        items = ", ".join(f'"{p}"' for p in data["disabled_providers"])
        lines.append(f"disabled_providers = [{items}]")

    lines.append("")

    routing = data.get("routing", {})
    if routing:
        lines.append("[routing]")
        if routing.get("default_provider"):
            lines.append(f'default_provider = "{routing["default_provider"]}"')
        lines.append("")

        for rule in routing.get("rules", []):
            lines.append("[[routing.rules]]")
            lines.append(f'provider = "{rule.get("provider", "")}"')
            match = rule.get("match", {})
            if match:
                lines.append("[routing.rules.match]")
                if match.get("keywords"):
                    kws = ", ".join(f'"{k}"' for k in match["keywords"])
                    lines.append(f"keywords = [{kws}]")
                if match.get("file_ext"):
                    exts = ", ".join(f'"{e}"' for e in match["file_ext"])
                    lines.append(f"file_ext = [{exts}]")
                if match.get("regex"):
                    lines.append(f'regex = "{match["regex"]}"')
            lines.append("")

    for name, profile in data.get("profiles", {}).items():
        lines.append(f"[profiles.{name}]")
        if isinstance(profile, dict):
            if profile.get("description"):
                lines.append(f'description = "{profile["description"]}"')
            for prov, pconf in profile.get("providers", {}).items():
                if isinstance(pconf, dict):
                    lines.append(f"[profiles.{name}.providers.{prov}]")
                    for k in ("model", "base_url", "api_key_env", "wire_api"):
                        if pconf.get(k):
                            lines.append(f'{k} = "{pconf[k]}"')
            lines.append("")

    return "\n".join(lines) + "\n"


class ConfigApp(App):
    """Vyane TUI configuration panel."""

    TITLE = "vyane config"

    CSS = """
    Screen {
        background: $surface;
    }
    .section {
        margin: 1 2;
        padding: 1 2;
        border: solid $primary;
        height: auto;
    }
    .section-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .field-label {
        margin: 1 0 0 0;
        padding: 0 2;
        text-style: bold;
        color: $text-muted;
    }
    Input {
        margin: 0 2;
    }
    Select {
        margin: 0 2;
    }
    .switch-row {
        layout: horizontal;
        height: 3;
        margin: 0 2;
    }
    .switch-row Label {
        width: 1fr;
        padding: 1 0;
    }
    .switch-row Switch {
        width: auto;
    }
    .rule-item {
        margin: 0 2;
        padding: 0 2;
        color: $text;
    }
    #save-bar {
        dock: bottom;
        height: 3;
        layout: horizontal;
        padding: 0 2;
        background: $boost;
    }
    #save-btn {
        margin: 0 1;
    }
    #save-status {
        padding: 1;
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, scope: str = "user"):
        super().__init__()
        self._scope = scope
        self._config_dir = (
            Path.cwd() / ".modelmux" if scope == "project" else user_config_dir()
        )
        self._toml_path = self._config_dir / "profiles.toml"
        self._policy_path = self._config_dir / "policy.json"
        self._raw = _load_raw(self._toml_path)
        self._policy_raw = self._load_policy()

    def _load_policy(self) -> dict:
        if not self._policy_path.exists():
            return {}
        try:
            return json.loads(self._policy_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Overview", id="tab-overview"):
                with VerticalScroll():
                    yield Static(self._render_overview(), id="overview-text")
            with TabPane("Routing", id="tab-routing"):
                with VerticalScroll():
                    yield Label("Default Provider", classes="field-label")
                    cur_default = self._raw.get("routing", {}).get(
                        "default_provider", "codex"
                    )
                    yield Select(
                        [(p, p) for p in PROVIDERS],
                        value=cur_default,
                        id="default-provider",
                    )
                    yield Horizontal(
                        Label("Auto-exclude caller"),
                        Switch(
                            value=self._raw.get("auto_exclude_caller", True),
                            id="auto-exclude",
                        ),
                        classes="switch-row",
                    )
                    yield Label(
                        "Disabled Providers (comma-separated)",
                        classes="field-label",
                    )
                    yield Input(
                        value=", ".join(self._raw.get("disabled_providers", [])),
                        id="disabled-providers",
                    )
                    yield Label(
                        "Caller Override (empty = auto-detect)",
                        classes="field-label",
                    )
                    yield Input(
                        value=self._raw.get("caller_override", ""),
                        id="caller-override",
                    )
                    # Show existing routing rules (read-only for now)
                    rules = self._raw.get("routing", {}).get("rules", [])
                    yield Label(
                        f"Routing Rules ({len(rules)} defined)",
                        classes="field-label",
                    )
                    for rule in rules:
                        kws = ", ".join(rule.get("match", {}).get("keywords", []))
                        prov = rule.get("provider", "?")
                        yield Static(f"  [{kws}] -> {prov}", classes="rule-item")
                    if not rules:
                        yield Static(
                            "  (none — using built-in keyword patterns)",
                            classes="rule-item",
                        )
            with TabPane("Policy", id="tab-policy"):
                with VerticalScroll():
                    yield Label(
                        "Max Calls Per Hour (0 = unlimited)",
                        classes="field-label",
                    )
                    yield Input(
                        value=str(self._policy_raw.get("max_calls_per_hour", 0)),
                        id="max-calls-hour",
                    )
                    yield Label(
                        "Max Calls Per Day (0 = unlimited)",
                        classes="field-label",
                    )
                    yield Input(
                        value=str(self._policy_raw.get("max_calls_per_day", 0)),
                        id="max-calls-day",
                    )
                    yield Label(
                        "Max Timeout Seconds (0 = unlimited)",
                        classes="field-label",
                    )
                    yield Input(
                        value=str(self._policy_raw.get("max_timeout", 0)),
                        id="max-timeout",
                    )
                    yield Label(
                        "Blocked Providers (comma-separated)",
                        classes="field-label",
                    )
                    yield Input(
                        value=", ".join(self._policy_raw.get("blocked_providers", [])),
                        id="blocked-providers",
                    )
                    yield Label(
                        "Blocked Sandboxes (comma-separated)",
                        classes="field-label",
                    )
                    yield Input(
                        value=", ".join(self._policy_raw.get("blocked_sandboxes", [])),
                        id="blocked-sandboxes",
                    )
        with Horizontal(id="save-bar"):
            yield Button("Save", id="save-btn", variant="primary")
            yield Static("", id="save-status")
        yield Footer()

    def _render_overview(self) -> str:
        lines = ["[bold cyan]CLI Availability[/]"]
        for name in PROVIDERS:
            binary = PROVIDER_INFO[name].get("binary")
            env_key = PROVIDER_INFO[name].get("env_key")
            if binary:
                path = shutil.which(binary)
                if path:
                    lines.append(f"  [green]+[/] {name:10s} {path}")
                else:
                    lines.append(f"  [yellow]-[/] {name:10s} not found")
            elif env_key:
                import os

                if os.environ.get(env_key, ""):
                    lines.append(f"  [green]+[/] {name:10s} API key set")
                else:
                    lines.append(f"  [yellow]-[/] {name:10s} {env_key} not set")

        lines.append("")
        lines.append("[bold cyan]Configuration[/]")
        lines.append(f"  Scope:    {self._scope}")
        lines.append(f"  File:     {self._toml_path}")
        exists = "yes" if self._toml_path.exists() else "no"
        lines.append(f"  Exists:   {exists}")

        routing = self._raw.get("routing", {})
        lines.append(f"  Default:  {routing.get('default_provider', 'codex')}")
        lines.append(f"  Rules:    {len(routing.get('rules', []))}")

        profiles = self._raw.get("profiles", {})
        if profiles:
            lines.append(f"  Profiles: {', '.join(profiles.keys())}")

        lines.append("")
        lines.append("[bold cyan]Policy[/]")
        if self._policy_path.exists():
            lines.append(f"  File:     {self._policy_path}")
            for k, v in self._policy_raw.items():
                lines.append(f"  {k}: {v}")
        else:
            lines.append("  No policy configured")

        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self.action_save()

    def action_save(self) -> None:
        """Save current configuration to disk."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        status = self.query_one("#save-status", Static)

        try:
            self._save_profiles()
            self._save_policy()
        except Exception as e:
            status.update(f"[red]Error: {e}[/]")
            return

        # Refresh overview
        self._raw = _load_raw(self._toml_path)
        self._policy_raw = self._load_policy()
        self.query_one("#overview-text", Static).update(self._render_overview())
        status.update(f"[green]Saved to {self._config_dir}[/]")

    def _save_profiles(self) -> None:
        """Collect routing fields and write profiles.toml."""
        select = self.query_one("#default-provider", Select)
        default_provider = select.value if select.value != Select.BLANK else "codex"
        auto_exclude = self.query_one("#auto-exclude", Switch).value
        disabled_raw = self.query_one("#disabled-providers", Input).value
        disabled = [p.strip() for p in disabled_raw.split(",") if p.strip()]
        caller_override = self.query_one("#caller-override", Input).value.strip()

        config = dict(self._raw)
        config["auto_exclude_caller"] = auto_exclude
        config["disabled_providers"] = disabled
        config["caller_override"] = caller_override
        config.setdefault("routing", {})["default_provider"] = default_provider

        self._toml_path.write_text(_generate_toml(config), encoding="utf-8")

    def _save_policy(self) -> None:
        """Collect policy fields and write policy.json."""
        policy: dict = {}

        max_hour = int(self.query_one("#max-calls-hour", Input).value or "0")
        max_day = int(self.query_one("#max-calls-day", Input).value or "0")
        max_timeout = int(self.query_one("#max-timeout", Input).value or "0")
        blocked_prov = self.query_one("#blocked-providers", Input).value
        blocked_sand = self.query_one("#blocked-sandboxes", Input).value

        if max_hour:
            policy["max_calls_per_hour"] = max_hour
        if max_day:
            policy["max_calls_per_day"] = max_day
        if max_timeout:
            policy["max_timeout"] = max_timeout

        bp = [p.strip() for p in blocked_prov.split(",") if p.strip()]
        if bp:
            policy["blocked_providers"] = bp
        bs = [s.strip() for s in blocked_sand.split(",") if s.strip()]
        if bs:
            policy["blocked_sandboxes"] = bs

        if policy:
            self._policy_path.write_text(
                json.dumps(policy, indent=2) + "\n", encoding="utf-8"
            )
        elif self._policy_path.exists():
            # All values cleared — remove policy file
            self._policy_path.unlink()


def run_tui(scope: str = "user") -> None:
    """Launch the TUI configuration panel."""
    app = ConfigApp(scope=scope)
    app.run()
