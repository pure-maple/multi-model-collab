"""Webhook notifications for dispatch events.

Sends POST requests to configured webhook URLs when dispatches complete.
Supports Slack, Discord, and generic webhook endpoints.

Configuration in profiles.toml:
    [notifications]
    webhook_url = "https://hooks.slack.com/services/..."
    # or Discord: "https://discord.com/api/webhooks/..."
    events = ["success", "error"]  # optional filter, default: all
    format = "slack"  # slack | discord | generic (auto-detected from URL)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass

logger = logging.getLogger("modelmux.notifications")


@dataclass
class NotificationConfig:
    """Webhook notification settings."""

    webhook_url: str = ""
    events: list[str] | None = None  # None = all events
    format: str = ""  # auto-detected if empty


def load_notification_config() -> NotificationConfig:
    """Load notification config from profiles or environment."""
    url = os.environ.get("MODELMUX_WEBHOOK_URL", "")
    if url:
        return NotificationConfig(webhook_url=url)

    try:
        from pathlib import Path

        from modelmux.config import _find_config_file, _load_file

        for cfg_dir in [
            Path.cwd() / ".modelmux",
            Path.home() / ".config" / "modelmux",
        ]:
            cfg_file = _find_config_file(cfg_dir)
            if cfg_file:
                data = _load_file(cfg_file)
                notif = data.get("notifications", {})
                if isinstance(notif, dict) and notif.get("webhook_url"):
                    return NotificationConfig(
                        webhook_url=notif["webhook_url"],
                        events=notif.get("events"),
                        format=notif.get("format", ""),
                    )
    except Exception:
        logger.debug("Failed to load notification config", exc_info=True)

    return NotificationConfig()


def _detect_format(url: str, explicit: str) -> str:
    """Detect webhook format from URL or explicit setting."""
    if explicit:
        return explicit
    if "hooks.slack.com" in url or "slack" in url:
        return "slack"
    if "discord.com/api/webhooks" in url:
        return "discord"
    return "generic"


def _build_payload(
    result: dict, task: str, source: str, fmt: str
) -> dict:
    """Build webhook payload based on format."""
    provider = result.get("provider", "unknown")
    status = result.get("status", "unknown")
    duration = result.get("duration_seconds", 0)
    summary = result.get("summary", "")[:200]
    icon = "\u2705" if status == "success" else "\u274c"

    title = f"{icon} modelmux {source}: {provider} ({status})"

    if fmt == "slack":
        return {
            "text": title,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*{title}*\n"
                            f"Duration: {duration:.1f}s\n"
                            f"Task: {task[:100]}\n"
                            f"Summary: {summary}"
                        ),
                    },
                }
            ],
        }

    if fmt == "discord":
        color = 0x3FB950 if status == "success" else 0xF85149
        return {
            "embeds": [
                {
                    "title": title,
                    "color": color,
                    "fields": [
                        {"name": "Provider", "value": provider, "inline": True},
                        {
                            "name": "Duration",
                            "value": f"{duration:.1f}s",
                            "inline": True,
                        },
                        {"name": "Task", "value": task[:100]},
                        {"name": "Summary", "value": summary},
                    ],
                }
            ]
        }

    # generic: simple JSON
    return {
        "event": f"modelmux.{source}.{status}",
        "provider": provider,
        "status": status,
        "duration_seconds": duration,
        "task": task[:200],
        "summary": summary,
    }


def _send_webhook(url: str, payload: dict) -> None:
    """Send webhook POST (fire-and-forget in background thread)."""
    try:
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.debug("Webhook failed: %s", e)


def notify_dispatch(result: dict, task: str, source: str = "dispatch") -> None:
    """Send webhook notification for a dispatch result (non-blocking)."""
    config = load_notification_config()
    if not config.webhook_url:
        return

    status = result.get("status", "")
    if config.events and status not in config.events:
        return

    fmt = _detect_format(config.webhook_url, config.format)
    payload = _build_payload(result, task, source, fmt)

    # Fire-and-forget in background thread to not block dispatch
    t = threading.Thread(
        target=_send_webhook,
        args=(config.webhook_url, payload),
        daemon=True,
    )
    t.start()
