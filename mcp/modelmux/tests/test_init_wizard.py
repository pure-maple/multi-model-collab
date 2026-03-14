"""Tests for the init wizard."""

import json as json_mod
import os
from unittest.mock import patch

import pytest

from vyane.init_wizard import (
    PROVIDER_INFO,
    PROVIDERS,
    _generate_toml,
    detect_clis,
    run_wizard,
)


class TestProviderInfo:
    """Verify provider metadata consistency."""

    def test_all_providers_have_info(self):
        for p in PROVIDERS:
            assert p in PROVIDER_INFO, f"{p} missing from PROVIDER_INFO"

    def test_provider_info_has_desc(self):
        for p, info in PROVIDER_INFO.items():
            assert "desc" in info
            assert "install" in info

    def test_dashscope_in_providers(self):
        assert "dashscope" in PROVIDERS

    def test_dashscope_has_env_key(self):
        assert PROVIDER_INFO["dashscope"].get("env_key") == "DASHSCOPE_CODING_API_KEY"
        assert PROVIDER_INFO["dashscope"].get("binary") is None


class TestDetectClis:
    """Test CLI/API detection."""

    def test_detects_available_binary(self):
        with patch("vyane.init_wizard.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/codex"
            with patch.dict("os.environ", {}, clear=True):
                result = detect_clis()
            assert result["codex"] is True

    def test_detects_missing_binary(self):
        with patch("vyane.init_wizard.shutil.which", return_value=None):
            with patch.dict("os.environ", {}, clear=True):
                result = detect_clis()
            assert result["codex"] is False
            assert result["gemini"] is False
            assert result["claude"] is False
            assert result["ollama"] is False

    def test_detects_dashscope_by_env(self):
        with patch("vyane.init_wizard.shutil.which", return_value=None):
            with patch.dict(
                "os.environ", {"DASHSCOPE_CODING_API_KEY": "sk-test"}, clear=True
            ):
                result = detect_clis()
            assert result["dashscope"] is True

    def test_dashscope_missing_without_env(self):
        with patch("vyane.init_wizard.shutil.which", return_value=None):
            with patch.dict("os.environ", {}, clear=True):
                result = detect_clis()
            assert result["dashscope"] is False


class TestGenerateToml:
    """Test TOML config generation."""

    def test_basic_config(self):
        toml = _generate_toml("codex", [])
        assert 'default_provider = "codex"' in toml
        assert "[routing]" in toml

    def test_with_routing_rules(self):
        rules = [{"provider": "gemini", "keywords": ["frontend", "CSS"]}]
        toml = _generate_toml("codex", rules)
        assert '[[routing.rules]]' in toml
        assert 'provider = "gemini"' in toml
        assert '"frontend"' in toml
        assert '"CSS"' in toml

    def test_with_profiles(self):
        profiles = [
            {
                "name": "budget",
                "description": "Use cheaper models",
                "providers": {
                    "codex": {"model": "gpt-4.1-mini"},
                },
            }
        ]
        toml = _generate_toml("codex", [], profiles)
        assert "[profiles.budget]" in toml
        assert 'description = "Use cheaper models"' in toml
        assert "[profiles.budget.providers.codex]" in toml
        assert 'model = "gpt-4.1-mini"' in toml

    def test_without_profiles_shows_example(self):
        toml = _generate_toml("codex", [])
        assert "# [profiles.budget]" in toml

    def test_with_profiles_no_example(self):
        profiles = [{"name": "test", "description": "", "providers": {}}]
        toml = _generate_toml("codex", [], profiles)
        assert "# [profiles.budget]" not in toml
        assert "[profiles.test]" in toml

    def test_multiple_profiles(self):
        profiles = [
            {"name": "fast", "description": "", "providers": {"codex": {"model": "gpt-4.1-mini"}}},
            {"name": "china", "description": "Chinese models", "providers": {"dashscope": {"model": "kimi-k2.5"}}},
        ]
        toml = _generate_toml("codex", [], profiles)
        assert "[profiles.fast]" in toml
        assert "[profiles.china]" in toml
        assert 'model = "kimi-k2.5"' in toml

    def test_profile_no_description(self):
        profiles = [{"name": "test", "description": "", "providers": {"codex": {"model": "m"}}}]
        toml = _generate_toml("codex", [], profiles)
        assert "[profiles.test]" in toml
        assert "description" not in toml.split("[profiles.test]")[1].split("\n")[1]

    def test_default_provider_gemini(self):
        toml = _generate_toml("gemini", [])
        assert 'default_provider = "gemini"' in toml

    def test_auto_exclude_caller(self):
        toml = _generate_toml("codex", [])
        assert "auto_exclude_caller = true" in toml

    def test_multiple_rules(self):
        rules = [
            {"provider": "codex", "keywords": ["api"]},
            {"provider": "gemini", "keywords": ["design"]},
        ]
        toml = _generate_toml("codex", rules)
        assert toml.count("[[routing.rules]]") == 2


# --- Helper functions ---


class TestHelperFunctions:
    def test_info_prints(self, capsys):
        from vyane.init_wizard import _info

        _info("test message")
        captured = capsys.readouterr()
        assert "test message" in captured.out

    def test_header_prints(self, capsys):
        from vyane.init_wizard import _header

        _header("Section Title")
        captured = capsys.readouterr()
        assert "Section Title" in captured.out

    def test_ask_with_default(self):
        from vyane.init_wizard import _ask

        with patch("builtins.input", return_value=""):
            result = _ask("prompt", "default_val")
            assert result == "default_val"

    def test_ask_with_input(self):
        from vyane.init_wizard import _ask

        with patch("builtins.input", return_value="custom"):
            result = _ask("prompt", "default_val")
            assert result == "custom"

    def test_ask_yn_default_yes(self):
        from vyane.init_wizard import _ask_yn

        with patch("builtins.input", return_value=""):
            assert _ask_yn("question", default=True) is True

    def test_ask_yn_default_no(self):
        from vyane.init_wizard import _ask_yn

        with patch("builtins.input", return_value=""):
            assert _ask_yn("question", default=False) is False

    def test_ask_yn_yes(self):
        from vyane.init_wizard import _ask_yn

        with patch("builtins.input", return_value="y"):
            assert _ask_yn("question", default=False) is True

    def test_ask_yn_no(self):
        from vyane.init_wizard import _ask_yn

        with patch("builtins.input", return_value="n"):
            assert _ask_yn("question", default=True) is False

    def test_ask_choice_by_name(self):
        from vyane.init_wizard import _ask_choice

        with patch("builtins.input", return_value="codex"):
            result = _ask_choice("pick", ["codex", "gemini"], "codex")
            assert result == "codex"

    def test_ask_choice_by_number(self):
        from vyane.init_wizard import _ask_choice

        with patch("builtins.input", return_value="2"):
            result = _ask_choice("pick", ["codex", "gemini"], "codex")
            assert result == "gemini"


# --- run_wizard ---


class TestRunWizard:
    def test_user_scope(self, tmp_path):
        """Wizard with user scope creates config in home dir."""
        inputs = iter([
            "codex",   # default provider choice
            "n",       # no routing rules
            "n",       # no profiles
            "n",       # no policy
        ])

        with (
            patch("vyane.init_wizard.shutil.which", return_value="/usr/bin/codex"),
            patch.dict("os.environ", {}, clear=True),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            run_wizard(scope="user")

        config_file = tmp_path / ".config" / "vyane" / "profiles.toml"
        assert config_file.exists()
        content = config_file.read_text()
        assert 'default_provider = "codex"' in content

    def test_project_scope(self, tmp_path):
        """Wizard with project scope creates .modelmux in cwd."""
        inputs = iter([
            "codex",
            "n",
            "n",
            "n",
        ])

        with (
            patch("vyane.init_wizard.shutil.which", return_value="/usr/bin/codex"),
            patch.dict("os.environ", {}, clear=True),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            run_wizard(scope="project")

        config_file = tmp_path / ".modelmux" / "profiles.toml"
        assert config_file.exists()

    def test_no_providers_detected(self, tmp_path):
        """When no CLIs found, wizard defaults to codex."""
        inputs = iter([
            "codex",
            "n",
            "n",
            "n",
        ])

        with (
            patch("vyane.init_wizard.shutil.which", return_value=None),
            patch.dict("os.environ", {}, clear=True),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            run_wizard(scope="user")

        config_file = tmp_path / ".config" / "vyane" / "profiles.toml"
        assert config_file.exists()

    def test_with_routing_rules(self, tmp_path):
        """Wizard creates config with routing rules."""
        inputs = iter([
            "codex",          # default provider
            "y",              # add routing rules
            "gemini",         # route to gemini
            "frontend, ui",   # keywords
            "n",              # no more rules
            "n",              # no profiles
            "n",              # no policy
        ])

        with (
            patch("vyane.init_wizard.shutil.which", return_value="/usr/bin/mock"),
            patch.dict("os.environ", {}, clear=True),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            run_wizard(scope="user")

        content = (tmp_path / ".config" / "vyane" / "profiles.toml").read_text()
        assert "[[routing.rules]]" in content
        assert '"frontend"' in content

    def test_with_policy(self, tmp_path):
        """Wizard creates policy.json when policy is configured."""
        inputs = iter([
            "codex",
            "n",       # no rules
            "n",       # no profiles
            "y",       # configure policy
            "100",     # max per hour
            "0",       # no day limit
            "y",       # block full sandbox
        ])

        with (
            patch("vyane.init_wizard.shutil.which", return_value="/usr/bin/mock"),
            patch.dict("os.environ", {}, clear=True),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            run_wizard(scope="user")

        policy_file = tmp_path / ".config" / "vyane" / "policy.json"
        assert policy_file.exists()
        policy = json_mod.loads(policy_file.read_text())
        assert policy["max_calls_per_hour"] == 100
        assert "full" in policy["blocked_sandboxes"]

    def test_overwrite_existing_yes(self, tmp_path):
        """Wizard overwrites existing config when user says yes."""
        config_dir = tmp_path / ".config" / "vyane"
        config_dir.mkdir(parents=True)
        existing = config_dir / "profiles.toml"
        existing.write_text("old content")

        inputs = iter([
            "codex",
            "n",
            "n",
            "n",
            "y",   # overwrite
        ])

        with (
            patch("vyane.init_wizard.shutil.which", return_value="/usr/bin/mock"),
            patch.dict("os.environ", {}, clear=True),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            run_wizard(scope="user")

        assert existing.read_text() != "old content"

    def test_overwrite_existing_no(self, tmp_path):
        """Wizard keeps existing config when user says no."""
        config_dir = tmp_path / ".config" / "vyane"
        config_dir.mkdir(parents=True)
        existing = config_dir / "profiles.toml"
        existing.write_text("old content")

        inputs = iter([
            "codex",
            "n",
            "n",
            "n",
            "n",   # don't overwrite
        ])

        with (
            patch("vyane.init_wizard.shutil.which", return_value="/usr/bin/mock"),
            patch.dict("os.environ", {}, clear=True),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            run_wizard(scope="user")

        assert existing.read_text() == "old content"

    def test_auto_scope_user(self, tmp_path):
        """Auto scope asks user for preference."""
        inputs = iter([
            "codex",
            "n",
            "n",
            "n",
            "user",   # choose user scope
        ])

        with (
            patch("vyane.init_wizard.shutil.which", return_value="/usr/bin/mock"),
            patch.dict("os.environ", {}, clear=True),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            run_wizard(scope="auto")

        config_file = tmp_path / ".config" / "vyane" / "profiles.toml"
        assert config_file.exists()
