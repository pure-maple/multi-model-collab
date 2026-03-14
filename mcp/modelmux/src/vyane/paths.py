"""Shared config/data path helpers for Vyane."""

from __future__ import annotations

from pathlib import Path


def user_config_dir() -> Path:
    """Return Vyane's primary user config directory."""
    return Path.home() / ".config" / "vyane"


def legacy_user_config_dir() -> Path:
    """Return the legacy modelmux user config directory."""
    return Path.home() / ".config" / "modelmux"


def user_config_search_dirs() -> tuple[Path, Path]:
    """Return user config directories in lookup order."""
    return (user_config_dir(), legacy_user_config_dir())


def resolve_user_read_path(*parts: str) -> Path:
    """Resolve a user data path with Vyane-first, modelmux fallback."""
    primary = user_config_dir().joinpath(*parts)
    legacy = legacy_user_config_dir().joinpath(*parts)
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def resolve_user_write_path(*parts: str) -> Path:
    """Resolve where new data should be written during the rename window."""
    primary = user_config_dir().joinpath(*parts)
    legacy = legacy_user_config_dir().joinpath(*parts)
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    if user_config_dir().exists():
        return primary
    if legacy_user_config_dir().exists():
        return legacy
    return primary
