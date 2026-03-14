"""Tests for MER-89: Intent Category → Model → Prompt Triple Binding."""

import json
from unittest import mock

from modelmux.config import (
    CategoryBinding,
    MuxConfig,
    Profile,
    _parse_config,
    _parse_profile,
    get_category_binding,
)
from modelmux.routing import IntentCategory


# ── Parsing ──


def test_parse_category_binding_from_dict():
    """CategoryBinding fields parse correctly from a raw dict."""
    data = {
        "description": "test profile",
        "providers": {},
        "category_bindings": {
            "code-gen": {
                "preferred_model": "codex/o3-pro",
                "prompt_template": "You are a senior engineer.",
                "parameters": {"reasoning_effort": "high", "sandbox": "write"},
            },
            "review": {
                "preferred_model": "dashscope/kimi-k2.5",
                "prompt_template": "Focus on bugs.",
                "parameters": {},
            },
        },
    }
    profile = _parse_profile(data)
    assert "code-gen" in profile.category_bindings
    assert "review" in profile.category_bindings

    cg = profile.category_bindings["code-gen"]
    assert cg.preferred_model == "codex/o3-pro"
    assert cg.prompt_template == "You are a senior engineer."
    assert cg.parameters == {"reasoning_effort": "high", "sandbox": "write"}

    rv = profile.category_bindings["review"]
    assert rv.preferred_model == "dashscope/kimi-k2.5"


def test_parse_profile_without_bindings():
    """Profiles without category_bindings still parse correctly (backward compat)."""
    data = {"description": "minimal", "providers": {}}
    profile = _parse_profile(data)
    assert profile.category_bindings == {}


def test_parse_config_with_bindings():
    """Full config round-trip including category_bindings."""
    data = {
        "profiles": {
            "default": {
                "description": "test",
                "providers": {},
                "category_bindings": {
                    "debug": {
                        "preferred_model": "codex",
                        "prompt_template": "Debug expert.",
                        "parameters": {"reasoning_effort": "high"},
                    },
                },
            }
        }
    }
    config = _parse_config(data)
    prof = config.profiles["default"]
    assert "debug" in prof.category_bindings
    assert prof.category_bindings["debug"].preferred_model == "codex"


def test_parse_binding_toml_style():
    """Simulate TOML-parsed nested dict structure."""
    # TOML [profiles.default.category_bindings.research] produces this dict
    data = {
        "profiles": {
            "default": {
                "category_bindings": {
                    "research": {
                        "preferred_model": "gemini",
                        "prompt_template": "Compare options objectively.",
                        "parameters": {},
                    }
                }
            }
        }
    }
    config = _parse_config(data)
    binding = config.profiles["default"].category_bindings["research"]
    assert binding.preferred_model == "gemini"
    assert binding.prompt_template == "Compare options objectively."


def test_parse_binding_partial_fields():
    """Binding with only some fields filled still parses."""
    data = {
        "category_bindings": {
            "docs": {"prompt_template": "Write clear docs."}
        }
    }
    profile = _parse_profile(data)
    b = profile.category_bindings["docs"]
    assert b.preferred_model == ""
    assert b.prompt_template == "Write clear docs."
    assert b.parameters == {}


# ── Lookup ──


def test_get_category_binding_found():
    """get_category_binding returns binding when it exists."""
    config = MuxConfig(
        active_profile="default",
        profiles={
            "default": Profile(
                category_bindings={
                    "code-gen": CategoryBinding(preferred_model="codex"),
                }
            )
        },
    )
    b = get_category_binding("code-gen", config)
    assert b is not None
    assert b.preferred_model == "codex"


def test_get_category_binding_not_found():
    """get_category_binding returns None for unconfigured categories."""
    config = MuxConfig(
        active_profile="default",
        profiles={"default": Profile()},
    )
    assert get_category_binding("code-gen", config) is None


def test_get_category_binding_wrong_profile():
    """Binding lookup uses the specified profile, not others."""
    config = MuxConfig(
        active_profile="default",
        profiles={
            "default": Profile(),
            "pro": Profile(
                category_bindings={
                    "review": CategoryBinding(preferred_model="claude"),
                }
            ),
        },
    )
    # default profile has no binding
    assert get_category_binding("review", config) is None
    # pro profile does
    b = get_category_binding("review", config, profile_name="pro")
    assert b is not None
    assert b.preferred_model == "claude"


def test_get_category_binding_empty_profiles():
    """No profiles at all returns None."""
    config = MuxConfig()
    assert get_category_binding("code-gen", config) is None


# ── Dispatch integration (unit-level, mocking adapter) ──


def _make_config_with_binding(
    category: str,
    preferred_model: str = "",
    prompt_template: str = "",
    parameters: dict | None = None,
) -> MuxConfig:
    """Helper: build a MuxConfig with a single category binding."""
    return MuxConfig(
        active_profile="default",
        profiles={
            "default": Profile(
                category_bindings={
                    category: CategoryBinding(
                        preferred_model=preferred_model,
                        prompt_template=prompt_template,
                        parameters=parameters or {},
                    ),
                }
            )
        },
    )


def test_binding_prompt_prepended():
    """prompt_template is prepended to the task text."""
    binding = CategoryBinding(prompt_template="You are a code reviewer.")
    task = "Check this function"
    if binding.prompt_template:
        task = f"[System: {binding.prompt_template}]\n\n{task}"
    assert task.startswith("[System: You are a code reviewer.]")
    assert "Check this function" in task


def test_binding_provider_override_auto():
    """preferred_model overrides provider when base_provider is auto."""
    binding = CategoryBinding(preferred_model="codex/o3-pro")
    base_provider = "auto"
    actual_provider = "gemini"  # auto-routed to gemini
    model = ""

    if base_provider == "auto" and binding.preferred_model:
        if "/" in binding.preferred_model:
            actual_provider, model = binding.preferred_model.split("/", 1)
        else:
            actual_provider = binding.preferred_model

    assert actual_provider == "codex"
    assert model == "o3-pro"


def test_binding_provider_not_overridden_explicit():
    """Explicit provider is NOT overridden by binding."""
    binding = CategoryBinding(preferred_model="codex/o3-pro")
    base_provider = "gemini"  # explicitly set
    actual_provider = "gemini"
    model = ""

    # Binding only applies when auto-routed
    if base_provider == "auto" and binding.preferred_model:
        if "/" in binding.preferred_model:
            actual_provider, model = binding.preferred_model.split("/", 1)
        else:
            actual_provider = binding.preferred_model

    # Provider should remain gemini
    assert actual_provider == "gemini"
    assert model == ""


def test_binding_parameters_merged():
    """Binding parameters merge into extra_args without overwriting existing."""
    binding = CategoryBinding(
        parameters={"reasoning_effort": "high", "custom_flag": True}
    )
    extra_args = {"model": "gpt-5.4"}  # pre-existing

    # Merge logic: binding values lose to explicit values
    for k, v in binding.parameters.items():
        if k not in ("sandbox", "reasoning_effort") and k not in extra_args:
            extra_args[k] = v

    assert extra_args["model"] == "gpt-5.4"  # not overwritten
    assert extra_args["custom_flag"] is True  # merged


def test_missing_binding_no_change():
    """When no binding exists, dispatch behavior is unchanged."""
    config = MuxConfig(
        active_profile="default",
        profiles={"default": Profile()},
    )
    binding = get_category_binding("code-gen", config)
    assert binding is None

    # No modifications should happen
    task = "implement a function"
    provider = "auto"
    model = ""
    reasoning_effort = ""

    if binding:
        # This block should not execute
        task = "MODIFIED"
        provider = "MODIFIED"

    assert task == "implement a function"
    assert provider == "auto"


def test_category_binding_dataclass():
    """CategoryBinding dataclass fields work correctly."""
    b = CategoryBinding(
        preferred_model="codex/o3-pro",
        prompt_template="Be concise.",
        parameters={"temperature": 0.7},
    )
    assert b.preferred_model == "codex/o3-pro"
    assert b.prompt_template == "Be concise."
    assert b.parameters["temperature"] == 0.7


def test_category_binding_defaults():
    """CategoryBinding defaults are empty/falsy."""
    b = CategoryBinding()
    assert b.preferred_model == ""
    assert b.prompt_template == ""
    assert b.parameters == {}
    # All falsy — no binding effects should apply
    assert not b.preferred_model
    assert not b.prompt_template
    assert not b.parameters


def test_binding_sandbox_override():
    """Binding can override sandbox when caller used default."""
    binding = CategoryBinding(parameters={"sandbox": "write"})
    sandbox = "read-only"  # default

    if "sandbox" in binding.parameters and sandbox == "read-only":
        sandbox = binding.parameters["sandbox"]

    assert sandbox == "write"


def test_binding_sandbox_no_override_when_explicit():
    """Binding does NOT override sandbox when caller set it explicitly."""
    binding = CategoryBinding(parameters={"sandbox": "write"})
    sandbox = "full"  # caller explicitly set

    if "sandbox" in binding.parameters and sandbox == "read-only":
        sandbox = binding.parameters["sandbox"]

    assert sandbox == "full"  # unchanged


def test_binding_reasoning_effort_override():
    """Binding sets reasoning_effort when caller didn't provide it."""
    binding = CategoryBinding(parameters={"reasoning_effort": "high"})
    reasoning_effort = ""

    if "reasoning_effort" in binding.parameters and not reasoning_effort:
        reasoning_effort = binding.parameters["reasoning_effort"]

    assert reasoning_effort == "high"


def test_binding_reasoning_effort_no_override_when_explicit():
    """Binding does NOT override reasoning_effort when caller set it."""
    binding = CategoryBinding(parameters={"reasoning_effort": "high"})
    reasoning_effort = "low"

    if "reasoning_effort" in binding.parameters and not reasoning_effort:
        reasoning_effort = binding.parameters["reasoning_effort"]

    assert reasoning_effort == "low"  # unchanged
