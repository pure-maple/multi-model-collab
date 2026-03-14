"""Tests for the adapters __init__ module (registry, custom providers, A2A agents)."""

from vyane.adapters import (
    ADAPTERS,
    A2ARemoteAdapter,
    GenericAdapter,
    _custom_adapters,
    get_all_adapters,
    load_custom_providers,
    register_a2a_agent,
    register_custom_provider,
)
from vyane.adapters.base import BaseAdapter


class TestAdaptersRegistry:
    def test_builtin_adapters(self):
        assert "codex" in ADAPTERS
        assert "gemini" in ADAPTERS
        assert "claude" in ADAPTERS
        assert "ollama" in ADAPTERS
        assert "dashscope" in ADAPTERS

    def test_all_are_base_adapter_subclasses(self):
        for name, cls in ADAPTERS.items():
            assert issubclass(cls, BaseAdapter), f"{name} not a BaseAdapter"


class TestRegisterCustomProvider:
    def setup_method(self):
        _custom_adapters.clear()

    def teardown_method(self):
        _custom_adapters.clear()

    def test_registers(self):
        register_custom_provider("mytool", "my-cli", args=["--prompt", "{task}"])
        assert "mytool" in _custom_adapters
        adapter = _custom_adapters["mytool"]
        assert isinstance(adapter, GenericAdapter)

    def test_with_description(self):
        register_custom_provider("t", "cmd", description="My tool")
        assert _custom_adapters["t"]._description == "My tool"


class TestRegisterA2AAgent:
    def setup_method(self):
        _custom_adapters.clear()

    def teardown_method(self):
        _custom_adapters.clear()

    def test_registers(self):
        register_a2a_agent("remote1", "http://localhost:41520")
        assert "remote1" in _custom_adapters
        adapter = _custom_adapters["remote1"]
        assert isinstance(adapter, A2ARemoteAdapter)

    def test_with_token_and_pattern(self):
        register_a2a_agent("r2", "http://x", token="secret", default_pattern="debate")
        adapter = _custom_adapters["r2"]
        assert adapter._token == "secret"
        assert adapter._default_pattern == "debate"


class TestGetAllAdapters:
    def setup_method(self):
        _custom_adapters.clear()

    def teardown_method(self):
        _custom_adapters.clear()

    def test_includes_builtins(self):
        result = get_all_adapters()
        for name in ADAPTERS:
            assert name in result

    def test_includes_custom(self):
        register_custom_provider("extra", "extra-cli")
        result = get_all_adapters()
        assert "extra" in result

    def test_does_not_modify_original(self):
        register_custom_provider("ext", "ext-cli")
        result = get_all_adapters()
        assert "ext" in result
        assert "ext" not in ADAPTERS


class TestLoadCustomProviders:
    def setup_method(self):
        _custom_adapters.clear()

    def teardown_method(self):
        _custom_adapters.clear()

    def test_loads_cli_provider(self):
        config = {
            "providers": {
                "mytest": {
                    "command": "my-test-cli",
                    "args": ["--run", "{task}"],
                    "description": "Test provider",
                }
            }
        }
        load_custom_providers(config)
        assert "mytest" in _custom_adapters

    def test_skips_builtin_names(self):
        config = {
            "providers": {
                "codex": {"command": "fake-codex"},
            }
        }
        load_custom_providers(config)
        assert "codex" not in _custom_adapters

    def test_skips_no_command(self):
        config = {
            "providers": {
                "bad": {"description": "no command"},
            }
        }
        load_custom_providers(config)
        assert "bad" not in _custom_adapters

    def test_skips_non_dict_provider(self):
        config = {
            "providers": {
                "bad": "not a dict",
            }
        }
        load_custom_providers(config)
        assert "bad" not in _custom_adapters

    def test_loads_a2a_agent(self):
        config = {
            "a2a_agents": {
                "agent1": {
                    "url": "http://localhost:8080",
                    "token": "tok",
                    "pattern": "consensus",
                }
            }
        }
        load_custom_providers(config)
        assert "agent1" in _custom_adapters

    def test_skips_a2a_no_url(self):
        config = {
            "a2a_agents": {
                "bad": {"token": "tok"},
            }
        }
        load_custom_providers(config)
        assert "bad" not in _custom_adapters

    def test_skips_a2a_non_dict(self):
        config = {
            "a2a_agents": {
                "bad": "string",
            }
        }
        load_custom_providers(config)
        assert "bad" not in _custom_adapters

    def test_empty_config(self):
        load_custom_providers({})
        assert len(_custom_adapters) == 0

    def test_non_dict_sections(self):
        load_custom_providers({"providers": "bad", "a2a_agents": "bad"})
        assert len(_custom_adapters) == 0
