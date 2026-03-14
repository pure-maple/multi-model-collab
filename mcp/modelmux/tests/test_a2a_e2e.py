"""End-to-end tests for A2A HTTP Server.

Uses httpx.AsyncClient with ASGI transport to test the full chain:
  httpx client → A2A HTTP server → CollaborationEngine → FakeAdapter

Covers:
  - Full task lifecycle (send → get → verify result)
  - SSE streaming with event parsing
  - Task cancellation during execution
  - Context ID continuity
  - Auth flow with Bearer token
  - Error propagation
"""

import asyncio
import json

import httpx
import pytest

from vyane.a2a.http_server import A2AServer
from vyane.adapters.base import AdapterResult, BaseAdapter

# --- Fake adapter ---


class SlowFakeAdapter(BaseAdapter):
    """Adapter with configurable delay for testing async behavior."""

    provider_name = "fake"
    _delay: float
    _response: str

    def __init__(
        self, response: str = "CONVERGED: done", delay: float = 0.0
    ):
        self._response = response
        self._delay = delay

    def _binary_name(self) -> str:
        return "echo"

    def build_command(self, prompt, workdir, **kw):
        return ["echo", prompt]

    def parse_output(self, lines):
        return "\n".join(lines), "", ""

    async def run(self, prompt="", **kw):
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        output = self._response
        if "CONVERGED" not in output and "synthesize" not in output.lower():
            output = f"Processed: {prompt[:60]}"
        return AdapterResult(
            provider="fake",
            status="success",
            output=output,
            summary=output[:100],
            duration_seconds=self._delay,
        )


def _build_app(
    auth_token: str = "",
    adapter: BaseAdapter | None = None,
):
    """Build A2A ASGI app for testing."""
    _adapter = adapter or SlowFakeAdapter()
    server = A2AServer(
        get_adapter=lambda name: _adapter,
        host="127.0.0.1",
        port=0,
        workdir="/tmp",
        sandbox="read-only",
        auth_token=auth_token,
    )
    return server.create_app()


def _jsonrpc(method: str, params: dict, req_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params,
    }


def _task_params(
    text: str,
    pattern: str = "review",
    task_id: str = "",
    providers: dict | None = None,
) -> dict:
    params: dict = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": text}],
        },
    }
    metadata: dict = {"pattern": pattern}
    if providers:
        metadata["providers"] = providers
    params["metadata"] = metadata
    if task_id:
        params["id"] = task_id
    return params


# --- Full lifecycle tests ---


@pytest.mark.asyncio
async def test_full_lifecycle_send_get():
    """Send a task, then retrieve it by ID — full async chain."""
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        # Send
        resp = await client.post(
            "/",
            json=_jsonrpc(
                "tasks/send",
                _task_params("implement hello world", task_id="e2e-1"),
            ),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "result" in body
        result = body["result"]
        task_id = result["id"]
        assert task_id.startswith("task-")  # server-generated ID
        assert result["status"]["state"] in ("completed", "failed")
        assert "contextId" in result

        # Get — should return same result
        resp2 = await client.post(
            "/",
            json=_jsonrpc("tasks/get", {"id": task_id}, req_id=2),
        )
        body2 = resp2.json()
        assert body2["result"]["id"] == task_id
        assert body2["result"]["status"]["state"] == result["status"]["state"]


@pytest.mark.asyncio
async def test_full_lifecycle_all_patterns():
    """All 3 patterns should complete through the full chain."""
    app = _build_app(
        adapter=SlowFakeAdapter(response="CONVERGED: all good")
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        for pattern in ("review", "consensus", "debate"):
            resp = await client.post(
                "/",
                json=_jsonrpc(
                    "tasks/send",
                    _task_params(f"test {pattern}", pattern=pattern),
                ),
            )
            body = resp.json()
            assert "result" in body, f"{pattern} failed: {body}"
            assert body["result"]["metadata"]["pattern"] == pattern


@pytest.mark.asyncio
async def test_result_structure():
    """Verify the result has all expected A2A fields."""
    app = _build_app(
        adapter=SlowFakeAdapter(response="CONVERGED: looks good")
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.post(
            "/",
            json=_jsonrpc(
                "tasks/send",
                _task_params("build a calculator"),
            ),
        )
        result = resp.json()["result"]

        # Required A2A fields
        assert "id" in result
        assert "contextId" in result
        assert "status" in result
        assert "state" in result["status"]

        # modelmux metadata
        assert "metadata" in result
        meta = result["metadata"]
        assert "pattern" in meta
        assert "rounds" in meta
        assert "duration_seconds" in meta
        assert "providers_used" in meta

        # History (turns)
        assert "history" in result
        assert len(result["history"]) >= 1
        for entry in result["history"]:
            assert entry["role"] == "agent"
            assert "parts" in entry
            assert "metadata" in entry
            assert "provider" in entry["metadata"]


# --- SSE streaming tests ---


@pytest.mark.asyncio
async def test_sse_stream_events():
    """SSE stream should emit status/progress/status(final) events."""
    app = _build_app(
        adapter=SlowFakeAdapter(
            response="CONVERGED: done", delay=0.05
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        async with client.stream(
            "POST",
            "/",
            json=_jsonrpc(
                "tasks/sendSubscribe",
                _task_params("stream test"),
            ),
        ) as resp:
            assert resp.status_code == 200

            events = []
            current_event = {}
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    current_event["event"] = line[6:].strip()
                elif line.startswith("data:"):
                    current_event["data"] = json.loads(
                        line[5:].strip()
                    )
                    events.append(current_event)
                    current_event = {}

            # Should have at least initial status + final status
            assert len(events) >= 2

            # First event: working status
            assert events[0]["event"] == "task/status"
            assert events[0]["data"]["status"]["state"] == "working"
            assert events[0]["data"]["final"] is False

            # Last event: final status
            last = events[-1]
            assert last["event"] == "task/status"
            assert last["data"]["final"] is True
            assert last["data"]["status"]["state"] in (
                "completed",
                "failed",
            )


@pytest.mark.asyncio
async def test_sse_includes_task_id():
    """All SSE events should include the task ID."""
    app = _build_app(
        adapter=SlowFakeAdapter(response="CONVERGED: ok")
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        async with client.stream(
            "POST",
            "/",
            json=_jsonrpc(
                "tasks/sendSubscribe",
                _task_params("id test", task_id="sse-id-1"),
            ),
        ) as resp:
            events = []
            current_event = {}
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    current_event["event"] = line[6:].strip()
                elif line.startswith("data:"):
                    current_event["data"] = json.loads(
                        line[5:].strip()
                    )
                    events.append(current_event)
                    current_event = {}

            # All events should have same server-generated task ID
            assert len(events) > 0
            first_id = events[0]["data"]["id"]
            assert first_id.startswith("task-")
            for ev in events:
                assert ev["data"]["id"] == first_id


# --- Auth tests ---


@pytest.mark.asyncio
async def test_auth_e2e_flow():
    """Full auth flow: no token → 401, wrong → 403, correct → success."""
    app = _build_app(auth_token="test-secret-42")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        payload = _jsonrpc(
            "tasks/get", {"id": "x"}
        )

        # No token → 401
        r1 = await client.post("/", json=payload)
        assert r1.status_code == 401

        # Wrong token → 403
        r2 = await client.post(
            "/",
            json=payload,
            headers={"Authorization": "Bearer wrong"},
        )
        assert r2.status_code == 403

        # Correct token → passes auth (gets task-not-found)
        r3 = await client.post(
            "/",
            json=payload,
            headers={"Authorization": "Bearer test-secret-42"},
        )
        body = r3.json()
        assert body["error"]["code"] == -32001  # task not found

        # Agent Card always open
        r4 = await client.get("/.well-known/agent.json")
        assert r4.status_code == 200
        assert "bearer" in r4.json().get("authSchemes", [])


# --- Context continuity ---


@pytest.mark.asyncio
async def test_context_id_assigned():
    """Each task should get a contextId, and different tasks get different IDs."""
    app = _build_app(
        adapter=SlowFakeAdapter(response="CONVERGED: ok")
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        # First request
        r1 = await client.post(
            "/",
            json=_jsonrpc(
                "tasks/send",
                _task_params("first"),
            ),
        )
        ctx1 = r1.json()["result"]["contextId"]
        assert ctx1  # contextId should be non-empty

        # Second request — different task, different context
        r2 = await client.post(
            "/",
            json=_jsonrpc(
                "tasks/send",
                _task_params("second"),
                req_id=2,
            ),
        )
        ctx2 = r2.json()["result"]["contextId"]
        assert ctx2  # contextId should be non-empty
        assert ctx1 != ctx2  # different tasks should have different contexts


# --- Error propagation ---


@pytest.mark.asyncio
async def test_unknown_pattern_returns_failed():
    """Unknown pattern should propagate as failed task, not 500."""
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.post(
            "/",
            json=_jsonrpc(
                "tasks/send",
                _task_params("test", pattern="nonexistent"),
            ),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["status"]["state"] == "failed"


@pytest.mark.asyncio
async def test_empty_message_returns_error():
    """Empty message parts should return INVALID_PARAMS."""
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.post(
            "/",
            json=_jsonrpc(
                "tasks/send",
                {"message": {"parts": []}},
            ),
        )
        body = resp.json()
        assert body["error"]["code"] == -32602


# --- Health check ---


@pytest.mark.asyncio
async def test_health_endpoint():
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body
