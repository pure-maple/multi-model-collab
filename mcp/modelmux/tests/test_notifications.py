"""Tests for webhook notification system."""

import json
from unittest.mock import MagicMock, patch

import pytest

from modelmux.notifications import (
    NotificationConfig,
    _build_payload,
    _detect_format,
    load_notification_config,
    notify_dispatch,
)


class TestDetectFormat:
    def test_explicit_format(self):
        assert _detect_format("https://example.com", "slack") == "slack"

    def test_slack_url(self):
        assert _detect_format("https://hooks.slack.com/services/T/B/x", "") == "slack"

    def test_discord_url(self):
        url = "https://discord.com/api/webhooks/123/abc"
        assert _detect_format(url, "") == "discord"

    def test_generic_url(self):
        assert _detect_format("https://example.com/webhook", "") == "generic"


class TestBuildPayload:
    def test_slack_format(self):
        result = {"provider": "codex", "status": "success", "duration_seconds": 5.2}
        payload = _build_payload(result, "review code", "dispatch", "slack")
        assert "text" in payload
        assert "blocks" in payload
        assert "codex" in payload["text"]
        assert "success" in payload["text"]

    def test_discord_format(self):
        result = {"provider": "gemini", "status": "error", "duration_seconds": 10}
        payload = _build_payload(result, "fix bug", "broadcast", "discord")
        assert "embeds" in payload
        embed = payload["embeds"][0]
        assert embed["color"] == 0xF85149  # red for error
        assert "gemini" in embed["title"]

    def test_discord_success_color(self):
        result = {"provider": "codex", "status": "success", "duration_seconds": 3}
        payload = _build_payload(result, "test", "dispatch", "discord")
        assert payload["embeds"][0]["color"] == 0x3FB950  # green

    def test_generic_format(self):
        result = {"provider": "ollama", "status": "success", "duration_seconds": 2}
        payload = _build_payload(result, "hello", "dispatch", "generic")
        assert payload["event"] == "modelmux.dispatch.success"
        assert payload["provider"] == "ollama"

    def test_task_truncation(self):
        long_task = "x" * 500
        result = {"provider": "codex", "status": "success", "duration_seconds": 1}
        payload = _build_payload(result, long_task, "dispatch", "generic")
        assert len(payload["task"]) <= 200


class TestLoadNotificationConfig:
    def test_from_env_var(self):
        with patch.dict("os.environ", {"MODELMUX_WEBHOOK_URL": "https://test.com/hook"}):
            config = load_notification_config()
        assert config.webhook_url == "https://test.com/hook"

    def test_empty_when_no_config(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "modelmux.config._find_config_file", return_value=None
            ):
                config = load_notification_config()
        assert config.webhook_url == ""


class TestNotifyDispatch:
    def test_no_url_does_nothing(self):
        with patch(
            "modelmux.notifications.load_notification_config",
            return_value=NotificationConfig(),
        ):
            # Should not raise
            notify_dispatch({"status": "success"}, task="test")

    def test_sends_webhook_on_success(self):
        config = NotificationConfig(webhook_url="https://test.com/hook")
        with patch(
            "modelmux.notifications.load_notification_config",
            return_value=config,
        ):
            with patch("modelmux.notifications._send_webhook") as mock_send:
                with patch("threading.Thread") as mock_thread:
                    mock_instance = MagicMock()
                    mock_thread.return_value = mock_instance
                    notify_dispatch(
                        {"provider": "codex", "status": "success"},
                        task="review",
                    )
                    mock_thread.assert_called_once()
                    mock_instance.start.assert_called_once()

    def test_event_filter_blocks(self):
        config = NotificationConfig(
            webhook_url="https://test.com/hook",
            events=["error"],
        )
        with patch(
            "modelmux.notifications.load_notification_config",
            return_value=config,
        ):
            with patch("threading.Thread") as mock_thread:
                notify_dispatch(
                    {"provider": "codex", "status": "success"},
                    task="test",
                )
                mock_thread.assert_not_called()

    def test_event_filter_allows(self):
        config = NotificationConfig(
            webhook_url="https://test.com/hook",
            events=["error"],
        )
        with patch(
            "modelmux.notifications.load_notification_config",
            return_value=config,
        ):
            with patch("threading.Thread") as mock_thread:
                mock_instance = MagicMock()
                mock_thread.return_value = mock_instance
                notify_dispatch(
                    {"provider": "codex", "status": "error"},
                    task="test",
                )
                mock_thread.assert_called_once()


class TestHistoryIntegration:
    """Verify log_result triggers notification."""

    def test_log_result_calls_notify(self, tmp_path):
        with patch("modelmux.history._history_file", return_value=tmp_path / "h.jsonl"):
            with patch("modelmux.notifications.notify_dispatch") as mock_notify:
                from modelmux.history import log_result

                log_result({"provider": "codex", "status": "success"}, task="test")
                mock_notify.assert_called_once_with(
                    {"provider": "codex", "status": "success"},
                    task="test",
                    source="dispatch",
                )
