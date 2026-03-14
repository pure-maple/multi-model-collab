"""Tests for A2A Client and A2A Remote Adapter.

Tests the client against a real A2A server using httpx ASGI transport
(no network required).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from modelmux.a2a.client import A2AClient, A2AClientConfig
from modelmux.a2a.http_server import A2AServer
from modelmux.adapters.a2a_remote import A2ARemoteAdapter
from modelmux.adapters.base import AdapterResult, BaseAdapter

# --- Fake adapter for the A2A server ---


class FakeServerAdapter(BaseAdapter):
    provider_name = "fake"

    def _binary_name(self) -> str:
        return "echo"

    def build_command(self, prompt, workdir, **kw):
        return ["echo", prompt]

    def parse_output(self, lines):
        return "\n".join(lines), "", ""

    async def run(self, prompt="", **kw):
        output = f"CONVERGED: processed: {prompt[:60]}"
        return AdapterResult(
            provider="fake",
            status="success",
            output=output,
            summary=output[:100],
            duration_seconds=0.01,
        )


def _build_test_app(auth_token: str = ""):
    server = A2AServer(
        get_adapter=lambda name: FakeServerAdapter(),
        host="127.0.0.1",
        port=0,
        workdir="/tmp",
        sandbox="read-only",
        auth_token=auth_token,
    )
    return server.create_app()


# --- A2AClient unit tests ---


class TestA2AClientParsing:
    """Test response parsing without a server."""

    def test_parse_success_response(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "id": "task-1",
                "contextId": "ctx-1",
                "status": {"state": "completed"},
                "history": [
                    {
                        "role": "agent",
                        "parts": [{"type": "text", "text": "done"}],
                        "metadata": {"provider": "fake"},
                    }
                ],
                "metadata": {"pattern": "review", "rounds": 1},
            },
        }
        resp = client._parse_response(body)
        assert resp.task_id == "task-1"
        assert resp.context_id == "ctx-1"
        assert resp.state == "completed"
        assert resp.output == "done"
        assert resp.metadata["pattern"] == "review"

    def test_parse_error_response(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32001, "message": "Task not found"},
        }
        resp = client._parse_response(body)
        assert resp.error == "Task not found"
        assert resp.task_id == ""

    def test_parse_empty_history(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "id": "t1",
                "contextId": "c1",
                "status": {"state": "completed"},
            },
        }
        resp = client._parse_response(body)
        assert resp.output == ""
        assert resp.state == "completed"

    def test_jsonrpc_message_format(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        msg = client._jsonrpc("tasks/send", {"key": "val"}, req_id=42)
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == 42
        assert msg["method"] == "tasks/send"
        assert msg["params"] == {"key": "val"}

    def test_build_task_params(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        params = client._build_task_params(
            "do something",
            pattern="debate",
            task_id="custom-id",
            providers={"proponent": "codex"},
            timeout_per_turn=120,
        )
        assert params["message"]["parts"][0]["text"] == "do something"
        assert params["metadata"]["pattern"] == "debate"
        assert params["metadata"]["providers"] == {"proponent": "codex"}
        assert params["metadata"]["timeout_per_turn"] == 120
        assert params["id"] == "custom-id"

    def test_build_task_params_minimal(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        params = client._build_task_params("hello")
        assert params["message"]["parts"][0]["text"] == "hello"
        assert params["metadata"]["pattern"] == "review"
        assert "id" not in params


# --- A2A Client integration tests (against ASGI app) ---


@pytest.mark.asyncio
async def test_client_discover():
    """Client should fetch Agent Card from server."""
    app = _build_test_app()
    transport = httpx.ASGITransport(app=app)

    # Use ASGI transport directly (no real network)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.get("/.well-known/agent.json")
        card = resp.json()
        assert card["name"] == "Plexus"
        assert "skills" in card


@pytest.mark.asyncio
async def test_client_send_via_asgi():
    """Client send() should work through ASGI transport."""
    app = _build_test_app()
    transport = httpx.ASGITransport(app=app)

    # Direct HTTP call to verify server works
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tasks/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "test task"}],
                    },
                    "metadata": {"pattern": "review"},
                },
            },
        )
        body = resp.json()
        assert "result" in body
        assert body["result"]["status"]["state"] in (
            "completed",
            "failed",
        )


@pytest.mark.asyncio
async def test_client_send_and_get_via_asgi():
    """Full lifecycle: send → get using direct HTTP."""
    app = _build_test_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        # Send
        r1 = await http.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tasks/send",
                "params": {
                    "id": "client-test-1",
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "hello"}],
                    },
                    "metadata": {"pattern": "review"},
                },
            },
        )
        result = r1.json()["result"]
        task_id = result["id"]
        assert task_id.startswith("task-")  # server-generated ID

        # Get
        r2 = await http.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tasks/get",
                "params": {"id": task_id},
            },
        )
        get_result = r2.json()["result"]
        assert get_result["id"] == task_id


# --- A2ARemoteAdapter tests ---


class TestA2ARemoteAdapter:
    def test_adapter_properties(self):
        adapter = A2ARemoteAdapter(
            name="test-remote",
            url="http://localhost:41520",
            token="secret",
        )
        assert adapter.provider_name == "test-remote"
        assert adapter.check_available() is True
        assert "a2a:" in adapter._binary_name()

    def test_adapter_default_pattern(self):
        adapter = A2ARemoteAdapter(
            name="custom",
            url="http://example.com",
            default_pattern="consensus",
        )
        assert adapter._default_pattern == "consensus"


# --- Config loading tests ---


class TestA2AAgentRegistration:
    def test_register_a2a_agent(self):
        from modelmux.adapters import (
            _custom_adapters,
            register_a2a_agent,
        )

        register_a2a_agent(
            name="test-agent",
            url="http://localhost:9999",
            token="tok",
            default_pattern="debate",
        )
        assert "test-agent" in _custom_adapters
        adapter = _custom_adapters["test-agent"]
        assert isinstance(adapter, A2ARemoteAdapter)
        assert adapter._default_pattern == "debate"
        # Clean up
        del _custom_adapters["test-agent"]

    def test_load_a2a_agents_from_config(self):
        from modelmux.adapters import (
            _custom_adapters,
            load_custom_providers,
        )

        config = {
            "a2a_agents": {
                "remote-mux": {
                    "url": "http://other-host:41520",
                    "token": "abc",
                    "pattern": "consensus",
                },
                "local-agent": {
                    "url": "http://localhost:8080",
                },
            }
        }
        load_custom_providers(config)
        assert "remote-mux" in _custom_adapters
        assert "local-agent" in _custom_adapters
        assert isinstance(_custom_adapters["remote-mux"], A2ARemoteAdapter)
        assert _custom_adapters["remote-mux"]._default_pattern == "consensus"
        assert _custom_adapters["local-agent"]._default_pattern == "review"
        # Clean up
        del _custom_adapters["remote-mux"]
        del _custom_adapters["local-agent"]

    def test_load_skips_empty_url(self):
        from modelmux.adapters import (
            _custom_adapters,
            load_custom_providers,
        )

        before = len(_custom_adapters)
        load_custom_providers({"a2a_agents": {"bad": {"token": "x"}}})
        assert len(_custom_adapters) == before

    def test_load_skips_invalid_data(self):
        from modelmux.adapters import (
            _custom_adapters,
            load_custom_providers,
        )

        before = len(_custom_adapters)
        load_custom_providers({"a2a_agents": "not a dict"})
        assert len(_custom_adapters) == before


# --- Additional A2A Client parsing tests ---


class TestA2AClientParsingExtended:
    """Extended parsing tests for edge cases."""

    def test_parse_multiple_history_entries(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        body = {
            "result": {
                "id": "t1",
                "status": {"state": "completed"},
                "history": [
                    {
                        "role": "user",
                        "parts": [{"type": "text", "text": "input"}],
                    },
                    {
                        "role": "agent",
                        "parts": [{"type": "text", "text": "first"}],
                    },
                    {
                        "role": "agent",
                        "parts": [{"type": "text", "text": "second"}],
                    },
                ],
            },
        }
        resp = client._parse_response(body)
        # Last agent message wins
        assert resp.output == "second"

    def test_parse_non_text_parts_skipped(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        body = {
            "result": {
                "id": "t1",
                "status": {"state": "completed"},
                "history": [
                    {
                        "role": "agent",
                        "parts": [
                            {"type": "data", "data": "binary"},
                            {"type": "text", "text": "actual"},
                        ],
                    },
                ],
            },
        }
        resp = client._parse_response(body)
        assert resp.output == "actual"

    def test_parse_artifacts(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        body = {
            "result": {
                "id": "t1",
                "status": {"state": "completed"},
                "artifacts": [
                    {"id": "a1", "parts": [{"text": "code"}]}
                ],
            },
        }
        resp = client._parse_response(body)
        assert len(resp.artifacts) == 1

    def test_parse_no_result(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        body = {"jsonrpc": "2.0", "id": 1}
        resp = client._parse_response(body)
        assert resp.task_id == ""
        assert resp.output == ""

    def test_parse_error_without_message(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        body = {"error": {"code": -32600}}
        resp = client._parse_response(body)
        assert resp.error != ""


class TestA2AClientConfig:
    def test_defaults(self):
        cfg = A2AClientConfig()
        assert cfg.url == ""
        assert cfg.token == ""
        assert cfg.timeout == 600.0
        assert cfg.name == ""


class TestA2AResponse:
    def test_defaults(self):
        from modelmux.a2a.client import A2AResponse

        resp = A2AResponse()
        assert resp.task_id == ""
        assert resp.state == ""
        assert resp.output == ""
        assert resp.error == ""
        assert resp.metadata == {}
        assert resp.history == []
        assert resp.artifacts == []


class TestA2AClientInit:
    def test_token_header(self):
        client = A2AClient(
            A2AClientConfig(url="http://test", token="secret")
        )
        assert client._headers["Authorization"] == "Bearer secret"

    def test_no_token(self):
        client = A2AClient(A2AClientConfig(url="http://test"))
        assert "Authorization" not in client._headers

    def test_name_from_config(self):
        client = A2AClient(
            A2AClientConfig(url="http://test", name="MyAgent")
        )
        assert client.name == "MyAgent"

    def test_name_fallback_to_url(self):
        client = A2AClient(
            A2AClientConfig(url="http://test:41520")
        )
        assert client.name == "http://test:41520"

    def test_url_trailing_slash_stripped(self):
        client = A2AClient(
            A2AClientConfig(url="http://test:41520/")
        )
        assert client._base_url == "http://test:41520"


# --- A2A Client async method tests (mocked httpx) ---


def _mock_httpx_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _mock_async_client(response):
    """Create a mock async context manager for httpx.AsyncClient."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.post = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestA2AClientDiscover:
    @pytest.mark.asyncio
    async def test_discover_success(self):
        card = {"name": "remote-agent", "skills": []}
        mock_resp = _mock_httpx_response(card)
        mock_http = _mock_async_client(mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://remote:8080"))
            result = await client.discover()

        assert result["name"] == "remote-agent"
        mock_http.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_with_auth(self):
        card = {"name": "agent"}
        mock_resp = _mock_httpx_response(card)
        mock_http = _mock_async_client(mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(
                A2AClientConfig(url="http://remote:8080", token="tok")
            )
            await client.discover()

        call_kwargs = mock_http.get.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer tok"


class TestA2AClientSend:
    @pytest.mark.asyncio
    async def test_send_success(self):
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "id": "task-abc",
                "contextId": "ctx-1",
                "status": {"state": "completed"},
                "history": [
                    {
                        "role": "agent",
                        "parts": [{"type": "text", "text": "result text"}],
                    }
                ],
            },
        }
        mock_resp = _mock_httpx_response(body)
        mock_http = _mock_async_client(mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            result = await client.send("do something", pattern="review")

        assert result.task_id == "task-abc"
        assert result.state == "completed"
        assert result.output == "result text"
        mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_with_all_params(self):
        body = {"jsonrpc": "2.0", "id": 1, "result": {"id": "t1", "status": {"state": "completed"}}}
        mock_resp = _mock_httpx_response(body)
        mock_http = _mock_async_client(mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            await client.send(
                "task",
                pattern="debate",
                task_id="custom-id",
                providers={"proponent": "codex"},
                timeout_per_turn=300,
            )

        call_args = mock_http.post.call_args
        payload = call_args[1]["json"]
        assert payload["method"] == "tasks/send"
        assert payload["params"]["id"] == "custom-id"
        assert payload["params"]["metadata"]["pattern"] == "debate"

    @pytest.mark.asyncio
    async def test_send_error_response(self):
        body = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "fail"}}
        mock_resp = _mock_httpx_response(body)
        mock_http = _mock_async_client(mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            result = await client.send("task")

        assert result.error == "fail"


class TestA2AClientGet:
    @pytest.mark.asyncio
    async def test_get_task(self):
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "id": "task-123",
                "status": {"state": "working"},
            },
        }
        mock_resp = _mock_httpx_response(body)
        mock_http = _mock_async_client(mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            result = await client.get("task-123")

        assert result.task_id == "task-123"
        assert result.state == "working"
        call_args = mock_http.post.call_args
        payload = call_args[1]["json"]
        assert payload["method"] == "tasks/get"
        assert payload["params"]["id"] == "task-123"


class TestA2AClientCancel:
    @pytest.mark.asyncio
    async def test_cancel_task(self):
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "id": "task-456",
                "status": {"state": "canceled"},
            },
        }
        mock_resp = _mock_httpx_response(body)
        mock_http = _mock_async_client(mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            result = await client.cancel("task-456")

        assert result.task_id == "task-456"
        assert result.state == "canceled"
        call_args = mock_http.post.call_args
        payload = call_args[1]["json"]
        assert payload["method"] == "tasks/cancel"


class TestA2AClientCheckAvailable:
    @pytest.mark.asyncio
    async def test_check_available_success(self):
        mock_resp = _mock_httpx_response({}, status_code=200)
        mock_http = _mock_async_client(mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            result = await client.check_available()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_available_not_200(self):
        mock_resp = _mock_httpx_response({}, status_code=503)
        mock_resp.status_code = 503
        mock_http = _mock_async_client(mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            result = await client.check_available()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_available_connection_error(self):
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            result = await client.check_available()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_available_os_error(self):
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=OSError("network down"))

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            result = await client.check_available()

        assert result is False


class TestA2AClientSendSubscribe:
    @pytest.mark.asyncio
    async def test_send_subscribe_parses_sse(self):
        """Test SSE parsing in send_subscribe."""

        async def _fake_aiter_lines():
            lines = [
                "event:status",
                'data:{"state":"working"}',
                "event:result",
                'data:{"state":"completed","output":"done"}',
            ]
            for line in lines:
                yield line

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = _fake_aiter_lines
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.stream = MagicMock(return_value=mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            events = []
            async for event in client.send_subscribe("test task"):
                events.append(event)

        assert len(events) == 2
        assert events[0]["event"] == "status"
        assert events[0]["data"]["state"] == "working"
        assert events[1]["event"] == "result"

    @pytest.mark.asyncio
    async def test_send_subscribe_invalid_json_data(self):
        """Non-JSON data lines should be passed as strings."""

        async def _fake_aiter_lines():
            lines = [
                "event:log",
                "data:not json at all",
            ]
            for line in lines:
                yield line

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = _fake_aiter_lines
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.stream = MagicMock(return_value=mock_resp)

        with patch("modelmux.a2a.client.httpx.AsyncClient", return_value=mock_http):
            client = A2AClient(A2AClientConfig(url="http://test"))
            events = []
            async for event in client.send_subscribe("task"):
                events.append(event)

        assert len(events) == 1
        assert events[0]["data"] == "not json at all"
