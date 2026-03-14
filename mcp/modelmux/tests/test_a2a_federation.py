"""Tests for A2A federation — two Vyane instances interconnected.

Verifies the concept of cross-instance routing:
  Instance A registers Instance B as an a2a_agent.
  Tasks dispatched to "instance-b" route through A2ARemoteAdapter.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vyane.a2a.client import A2AClient, A2AClientConfig, A2AResponse
from vyane.adapters import (
    A2ARemoteAdapter,
    get_all_adapters,
    load_custom_providers,
    register_a2a_agent,
)
from vyane.adapters import _custom_adapters


@pytest.fixture(autouse=True)
def clean_custom_adapters():
    """Ensure custom adapters are clean before each test."""
    _custom_adapters.clear()
    yield
    _custom_adapters.clear()


class TestFederationRegistration:
    """Test that remote Vyane instances can be registered as providers."""

    def test_register_remote_instance(self):
        register_a2a_agent(
            name="instance-b",
            url="http://localhost:41520",
            token="secret-b",
            default_pattern="review",
        )
        all_adapters = get_all_adapters()
        assert "instance-b" in all_adapters
        adapter = all_adapters["instance-b"]
        assert isinstance(adapter, A2ARemoteAdapter)
        assert adapter.provider_name == "instance-b"

    def test_register_via_config(self):
        config = {
            "a2a_agents": {
                "remote-mux-1": {
                    "url": "http://192.168.1.100:41520",
                    "token": "shared-secret",
                    "pattern": "consensus",
                },
                "remote-mux-2": {
                    "url": "http://192.168.1.101:41520",
                },
            }
        }
        load_custom_providers(config)
        all_adapters = get_all_adapters()
        assert "remote-mux-1" in all_adapters
        assert "remote-mux-2" in all_adapters

    def test_bidirectional_registration(self):
        """Both instances can register each other."""
        register_a2a_agent("mux-alpha", "http://alpha:41520", token="a")
        register_a2a_agent("mux-beta", "http://beta:41520", token="b")
        all_adapters = get_all_adapters()
        assert "mux-alpha" in all_adapters
        assert "mux-beta" in all_adapters

    def test_federation_does_not_shadow_builtins(self):
        """A2A agents cannot override built-in adapters."""
        register_a2a_agent("custom-agent", "http://remote:41520")
        all_adapters = get_all_adapters()
        # Built-ins are still present
        assert "codex" in all_adapters
        assert "gemini" in all_adapters
        assert "claude" in all_adapters
        # Custom agent coexists
        assert "custom-agent" in all_adapters


class TestFederationRouting:
    """Test that tasks can route to remote instances."""

    @pytest.mark.asyncio
    async def test_dispatch_to_remote(self):
        """Dispatch to a remote instance via A2ARemoteAdapter."""
        adapter = A2ARemoteAdapter(
            name="remote-mux",
            url="http://localhost:41520",
            token="test",
        )

        mock_response = A2AResponse(
            task_id="task-1",
            context_id="ctx-1",
            state="completed",
            output="Remote instance completed the task successfully.",
        )

        with patch.object(
            adapter._client, "check_available", new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = True
            with patch.object(
                adapter._client, "send", new_callable=AsyncMock
            ) as mock_send:
                mock_send.return_value = mock_response
                result = await adapter.run(
                    prompt="Implement a rate limiter",
                    workdir="/tmp",
                    timeout=120,
                )

        assert result.status == "success"
        assert result.output == "Remote instance completed the task successfully."
        assert result.session_id == "ctx-1"
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_to_unreachable_remote(self):
        """Should return error when remote instance is unreachable."""
        adapter = A2ARemoteAdapter(
            name="offline-mux",
            url="http://unreachable:41520",
        )

        with patch.object(
            adapter._client, "check_available", new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = False
            result = await adapter.run(prompt="test task")

        assert result.status == "error"
        assert "unreachable" in result.error.lower()

    @pytest.mark.asyncio
    async def test_dispatch_with_pattern(self):
        """Extra args should pass pattern to remote instance."""
        adapter = A2ARemoteAdapter(
            name="remote-mux",
            url="http://localhost:41520",
            default_pattern="review",
        )

        mock_response = A2AResponse(
            task_id="task-2",
            state="completed",
            output="Consensus achieved.",
        )

        with patch.object(
            adapter._client, "check_available", new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = True
            with patch.object(
                adapter._client, "send", new_callable=AsyncMock
            ) as mock_send:
                mock_send.return_value = mock_response
                result = await adapter.run(
                    prompt="Evaluate migration strategy",
                    extra_args={"pattern": "consensus"},
                )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        assert call_kwargs[1].get("pattern", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else "") == "consensus" or mock_send.call_args_list[0][1].get("pattern") == "consensus"


class TestFederationAgentCard:
    """Test Agent Card discovery for federation."""

    @pytest.mark.asyncio
    async def test_discover_remote_agent_card(self):
        """Can fetch Agent Card from remote instance."""
        client = A2AClient(
            A2AClientConfig(url="http://localhost:41520", name="remote")
        )

        mock_card = {
            "name": "vyane-beta",
            "description": "Remote Vyane instance",
            "url": "http://beta:41520",
            "version": "0.24.0",
            "capabilities": {"streaming": True, "pushNotifications": True},
            "skills": [
                {"id": "dispatch", "name": "mux_dispatch"},
                {"id": "collaborate", "name": "mux_collaborate"},
            ],
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=mock_instance
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_card
            mock_resp.raise_for_status = MagicMock()
            mock_instance.get = AsyncMock(return_value=mock_resp)

            card = await client.discover()

        assert card["name"] == "vyane-beta"
        assert len(card["skills"]) == 2


class TestFederationTaskRouting:
    """Test the full routing chain from config to dispatch."""

    def test_config_to_adapter_chain(self):
        """End-to-end: config → register → get_all_adapters → dispatch ready."""
        config = {
            "a2a_agents": {
                "peer-instance": {
                    "url": "http://10.0.0.5:41520",
                    "token": "federation-key",
                    "pattern": "review",
                }
            }
        }
        load_custom_providers(config)

        all_adapters = get_all_adapters()
        adapter = all_adapters.get("peer-instance")
        assert adapter is not None
        assert isinstance(adapter, A2ARemoteAdapter)
        assert adapter._url == "http://10.0.0.5:41520"
        assert adapter._token == "federation-key"

    def test_multiple_federated_instances(self):
        """Can register multiple remote instances."""
        for i in range(5):
            register_a2a_agent(
                f"node-{i}",
                f"http://node-{i}:41520",
                token=f"key-{i}",
            )

        all_adapters = get_all_adapters()
        remote_count = sum(
            1
            for a in all_adapters.values()
            if isinstance(a, A2ARemoteAdapter)
        )
        assert remote_count == 5
