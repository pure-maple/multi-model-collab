"""Tests for A2A HTTP Server."""


from starlette.testclient import TestClient

from modelmux.a2a.http_server import (
    A2AServer,
    InvalidParamsError,
    TaskStore,
    _extract_task_params,
)
from modelmux.adapters.base import AdapterResult, BaseAdapter

# --- Fake adapter for testing ---


class FakeAdapter(BaseAdapter):
    provider_name = "fake"

    def _binary_name(self) -> str:
        return "echo"

    def build_command(self, prompt, workdir, **kw):
        return ["echo", prompt]

    def parse_output(self, lines):
        return "\n".join(lines), "", ""

    async def run(self, prompt="", **kw):
        if "CONVERGED" in prompt or "synthesize" in prompt.lower():
            output = "CONVERGED: looks good\n\nAll criteria met."
        else:
            output = f"Fake response to: {prompt[:80]}"
        return AdapterResult(
            provider="fake",
            status="success",
            output=output,
            summary=output[:100],
            duration_seconds=0.1,
        )


def _get_fake_adapter(name: str) -> BaseAdapter:
    return FakeAdapter()


def _make_client(auth_token: str = "") -> TestClient:
    server = A2AServer(
        get_adapter=_get_fake_adapter,
        host="127.0.0.1",
        port=0,
        workdir="/tmp",
        sandbox="read-only",
        auth_token=auth_token,
    )
    app = server.create_app()
    return TestClient(app)


# --- Agent Card Tests ---


def test_agent_card_endpoint():
    client = _make_client()
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "modelmux"
    assert card["protocolVersion"] == "0.3.0"
    assert "skills" in card
    assert "capabilities" in card
    assert card["capabilities"]["streaming"] is True


def test_agent_card_has_skills():
    client = _make_client()
    card = client.get("/.well-known/agent.json").json()
    skill_names = [s["name"] for s in card["skills"]]
    assert any("review" in n for n in skill_names)
    assert any("consensus" in n for n in skill_names)
    assert any("debate" in n for n in skill_names)


# --- JSON-RPC Validation Tests ---


def test_invalid_json():
    client = _make_client()
    resp = client.post(
        "/",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32700


def test_invalid_jsonrpc_version():
    client = _make_client()
    resp = client.post(
        "/",
        json={"jsonrpc": "1.0", "id": 1, "method": "tasks/get", "params": {}},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32600


def test_unknown_method():
    client = _make_client()
    resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 1, "method": "unknown/method", "params": {}},
    )
    body = resp.json()
    assert body["error"]["code"] == -32601


# --- TaskStore Tests ---


def test_task_store_create():
    store = TaskStore()
    entry = store.create()
    assert entry.task_id.startswith("task-")
    assert entry.context_id.startswith("ctx-")
    assert entry.state == "submitted"


def test_task_store_get():
    store = TaskStore()
    entry = store.create(task_id="test-123")
    assert store.get("test-123") is entry
    assert store.get("nonexistent") is None


def test_task_store_update():
    store = TaskStore()
    entry = store.create(task_id="test-456")
    store.update("test-456", state="working")
    assert entry.state == "working"


def test_task_store_eviction():
    store = TaskStore(max_tasks=3)
    for i in range(5):
        e = store.create(task_id=f"task-{i}")
        e.state = "completed"
    # Should have evicted oldest completed tasks
    assert len(store._tasks) <= 3


# --- _extract_task_params Tests ---


def test_extract_task_params_basic():
    params = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": "implement a REST API"}],
        }
    }
    tp = _extract_task_params(params)
    assert tp.task_text == "implement a REST API"
    assert tp.pattern == "review"  # default
    assert tp.provider_map is None
    assert tp.timeout_per_turn == 0


def test_extract_task_params_with_metadata():
    params = {
        "message": {
            "role": "user",
            "parts": [{"text": "analyze this code"}],
        },
        "metadata": {
            "pattern": "consensus",
            "providers": {"analyst_impl": "codex"},
            "timeout_per_turn": 120,
        },
    }
    tp = _extract_task_params(params)
    assert tp.task_text == "analyze this code"
    assert tp.pattern == "consensus"
    assert tp.provider_map == {"analyst_impl": "codex"}
    assert tp.timeout_per_turn == 120


def test_extract_task_params_empty_message():
    try:
        _extract_task_params({"message": {"parts": []}})
        assert False, "Should have raised"
    except InvalidParamsError:
        pass


# --- tasks/get Tests ---


def test_tasks_get_not_found():
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/get",
            "params": {"id": "nonexistent"},
        },
    )
    body = resp.json()
    assert body["error"]["code"] == -32001


def test_tasks_get_missing_id():
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/get",
            "params": {},
        },
    )
    body = resp.json()
    assert body["error"]["code"] == -32602


# --- tasks/send Tests ---


def test_tasks_send_basic():
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "hello world"}],
                },
                "metadata": {"pattern": "review"},
            },
        },
    )
    body = resp.json()
    assert "result" in body
    result = body["result"]
    assert "id" in result
    assert "contextId" in result
    assert result["status"]["state"] in ("completed", "failed")
    assert result["metadata"]["pattern"] == "review"


# --- tasks/cancel Tests ---


def test_tasks_cancel_not_found():
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/cancel",
            "params": {"id": "nonexistent"},
        },
    )
    body = resp.json()
    assert body["error"]["code"] == -32001


# --- tasks/send → tasks/get E2E ---


def test_e2e_send_then_get():
    """Full lifecycle: send a task, then retrieve it by ID."""
    client = _make_client()

    # Send
    send_resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "id": "e2e-test-001",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "implement hello world"}],
                },
                "metadata": {"pattern": "review"},
            },
        },
    )
    send_body = send_resp.json()
    assert "result" in send_body
    task_id = send_body["result"]["id"]
    assert task_id == "e2e-test-001"

    # Get
    get_resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tasks/get",
            "params": {"id": task_id},
        },
    )
    get_body = get_resp.json()
    assert "result" in get_body
    result = get_body["result"]
    assert result["id"] == task_id
    assert result["status"]["state"] in ("completed", "failed")
    assert "metadata" in result
    assert result["metadata"]["pattern"] == "review"


def test_e2e_send_consensus_pattern():
    """Verify consensus pattern runs through HTTP."""
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [
                        {"type": "text", "text": "evaluate microservices vs monolith"}
                    ],
                },
                "metadata": {"pattern": "consensus"},
            },
        },
    )
    body = resp.json()
    assert "result" in body
    result = body["result"]
    assert result["metadata"]["pattern"] == "consensus"
    assert result["metadata"]["rounds"] >= 1


def test_e2e_send_debate_pattern():
    """Verify debate pattern runs through HTTP."""
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "should we use Rust or Go?"}],
                },
                "metadata": {"pattern": "debate"},
            },
        },
    )
    body = resp.json()
    assert "result" in body
    result = body["result"]
    assert result["metadata"]["pattern"] == "debate"


def test_e2e_send_with_provider_override():
    """Verify provider mapping is passed through."""
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "write tests"}],
                },
                "metadata": {
                    "pattern": "review",
                    "providers": {"implementer": "fake", "reviewer": "fake"},
                },
            },
        },
    )
    body = resp.json()
    assert "result" in body
    assert body["result"]["status"]["state"] in ("completed", "failed")


def test_e2e_result_has_history():
    """Verify the result includes turn history."""
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "build a calculator"}],
                },
                "metadata": {"pattern": "review"},
            },
        },
    )
    result = resp.json()["result"]
    assert "history" in result
    assert len(result["history"]) >= 1
    # Each history entry should have A2A-compliant structure
    for entry in result["history"]:
        assert entry["role"] == "agent"
        assert "parts" in entry
        assert entry["parts"][0]["type"] == "text"


# --- tasks/cancel with active task ---


def test_cancel_completed_task_is_noop():
    """Canceling an already-completed task returns current state."""
    client = _make_client()
    # First send to create a completed task
    client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "id": "cancel-test-001",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "do something"}],
                },
            },
        },
    )
    # Now cancel it
    cancel_resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tasks/cancel",
            "params": {"id": "cancel-test-001"},
        },
    )
    body = cancel_resp.json()
    assert "result" in body
    # Should return the terminal state, not "canceled"
    assert body["result"]["status"]["state"] in ("completed", "failed")


# --- Edge cases ---


def test_missing_message_field():
    """Sending without message field should error."""
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {"metadata": {"pattern": "review"}},
        },
    )
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == -32602


def test_unknown_pattern_in_send():
    """Unknown pattern should still return a result (engine handles it)."""
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "test"}],
                },
                "metadata": {"pattern": "nonexistent_pattern"},
            },
        },
    )
    body = resp.json()
    # Engine should return failed state for unknown pattern
    assert "result" in body
    assert body["result"]["status"]["state"] == "failed"


def test_jsonrpc_id_preserved():
    """Response id should match request id."""
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "my-custom-id-42",
            "method": "tasks/get",
            "params": {"id": "nonexistent"},
        },
    )
    body = resp.json()
    assert body["id"] == "my-custom-id-42"


def test_multi_part_message():
    """Multiple text parts should be concatenated."""
    params = {
        "message": {
            "role": "user",
            "parts": [
                {"type": "text", "text": "First part. "},
                {"type": "text", "text": "Second part."},
            ],
        }
    }
    tp = _extract_task_params(params)
    assert tp.task_text == "First part. Second part."


# --- tasks/sendSubscribe Tests ---


def test_tasks_send_subscribe():
    client = _make_client()
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/sendSubscribe",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "quick test"}],
                },
                "metadata": {"pattern": "review"},
            },
        },
    )
    # SSE response
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


# --- Authentication Tests ---


def test_auth_agent_card_always_open():
    """Agent Card endpoint should be accessible even when auth is enabled."""
    client = _make_client(auth_token="secret-token-123")
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "modelmux"
    assert "bearer" in card.get("authSchemes", [])


def test_auth_required_no_token():
    """Without token, authed server should reject requests."""
    client = _make_client(auth_token="secret-token-123")
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/get",
            "params": {"id": "test"},
        },
    )
    assert resp.status_code == 401


def test_auth_wrong_token():
    """Wrong token should get 403."""
    client = _make_client(auth_token="secret-token-123")
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/get",
            "params": {"id": "test"},
        },
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 403


def test_auth_correct_token():
    """Correct token should allow request through."""
    client = _make_client(auth_token="secret-token-123")
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/get",
            "params": {"id": "nonexistent"},
        },
        headers={"Authorization": "Bearer secret-token-123"},
    )
    # Should get through auth and hit the normal error (task not found)
    body = resp.json()
    assert body["error"]["code"] == -32001  # TASK_NOT_FOUND, not auth error


def test_no_auth_when_not_configured():
    """Without auth_token, all requests should pass through."""
    client = _make_client()  # no token
    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/get",
            "params": {"id": "test"},
        },
    )
    # Should hit TASK_NOT_FOUND, not auth error
    body = resp.json()
    assert body["error"]["code"] == -32001


def test_agent_card_no_auth_schemes_when_disabled():
    """Agent Card should not list authSchemes when auth is disabled."""
    client = _make_client()  # no token
    card = client.get("/.well-known/agent.json").json()
    assert "authSchemes" not in card


# --- TaskStore Persistence Tests ---


def test_task_store_persist_on_terminal_state(tmp_path):
    """Completed tasks should be appended to JSONL file."""
    import json

    persist_file = tmp_path / "tasks.jsonl"
    store = TaskStore(persist_path=str(persist_file))
    entry = store.create(task_id="persist-1")
    result = {"status": {"state": "completed"}}
    store.update("persist-1", state="completed", result=result)

    assert persist_file.exists()
    lines = persist_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["task_id"] == "persist-1"
    assert record["state"] == "completed"
    assert record["result"] == {"status": {"state": "completed"}}
    assert record["context_id"] == entry.context_id


def test_task_store_persist_multiple_terminal_states(tmp_path):
    """Multiple terminal tasks should each be persisted."""
    import json

    persist_file = tmp_path / "tasks.jsonl"
    store = TaskStore(persist_path=str(persist_file))
    for i, state in enumerate(["completed", "failed", "canceled"]):
        store.create(task_id=f"multi-{i}")
        store.update(f"multi-{i}", state=state)

    lines = persist_file.read_text().strip().splitlines()
    assert len(lines) == 3
    states = [json.loads(line)["state"] for line in lines]
    assert states == ["completed", "failed", "canceled"]


def test_task_store_no_persist_for_working_state(tmp_path):
    """Non-terminal states should not trigger persistence."""
    persist_file = tmp_path / "tasks.jsonl"
    store = TaskStore(persist_path=str(persist_file))
    store.create(task_id="working-1")
    store.update("working-1", state="working")

    assert not persist_file.exists()


def test_task_store_no_persist_without_path():
    """No file operations when persist_path is empty."""
    store = TaskStore(persist_path="")
    entry = store.create(task_id="no-persist-1")
    store.update("no-persist-1", state="completed")
    # Should not raise — just silently skip persistence
    assert entry.state == "completed"


def test_task_store_load_from_disk(tmp_path):
    """Tasks persisted to JSONL should be loaded on startup."""
    import json

    persist_file = tmp_path / "tasks.jsonl"
    records = [
        {
            "task_id": "loaded-1",
            "context_id": "ctx-abc",
            "state": "completed",
            "created_at": 1000.0,
            "updated_at": 1001.0,
            "result": {"id": "loaded-1", "status": {"state": "completed"}},
        },
        {
            "task_id": "loaded-2",
            "context_id": "ctx-def",
            "state": "failed",
            "created_at": 2000.0,
            "updated_at": 2001.0,
            "result": None,
        },
    ]
    persist_file.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    store = TaskStore(persist_path=str(persist_file))
    assert store.get("loaded-1") is not None
    assert store.get("loaded-1").context_id == "ctx-abc"
    assert store.get("loaded-1").state == "completed"
    expected = {"id": "loaded-1", "status": {"state": "completed"}}
    assert store.get("loaded-1").result == expected

    assert store.get("loaded-2") is not None
    assert store.get("loaded-2").state == "failed"


def test_task_store_load_skips_duplicates(tmp_path):
    """In-memory tasks should not be overwritten by disk data."""
    import json

    persist_file = tmp_path / "tasks.jsonl"
    persist_file.write_text(
        json.dumps(
            {
                "task_id": "dup-1",
                "context_id": "ctx-old",
                "state": "completed",
                "created_at": 0,
                "updated_at": 0,
                "result": None,
            }
        )
        + "\n"
    )

    store = TaskStore(persist_path=str(persist_file))
    assert store.get("dup-1") is not None
    assert store.get("dup-1").context_id == "ctx-old"

    # Loading again should not create duplicates
    store._load_from_disk()
    assert store.get("dup-1").context_id == "ctx-old"


def test_task_store_load_handles_missing_file(tmp_path):
    """Missing persistence file should not cause errors."""
    persist_file = tmp_path / "nonexistent.jsonl"
    store = TaskStore(persist_path=str(persist_file))
    assert store.get("anything") is None


def test_task_store_load_handles_corrupt_file(tmp_path):
    """Corrupt JSONL should not crash — gracefully skip."""
    persist_file = tmp_path / "corrupt.jsonl"
    persist_file.write_text("not valid json\n{also bad\n")

    store = TaskStore(persist_path=str(persist_file))
    # Should not raise, just log warning
    assert len(store._tasks) == 0


def test_task_store_load_skips_blank_lines(tmp_path):
    """Blank lines in JSONL should be silently skipped."""
    import json

    persist_file = tmp_path / "blanks.jsonl"
    content = (
        json.dumps({"task_id": "blank-1", "context_id": "c", "state": "completed",
                     "created_at": 0, "updated_at": 0, "result": None})
        + "\n\n\n"
        + json.dumps({"task_id": "blank-2", "context_id": "d", "state": "failed",
                     "created_at": 0, "updated_at": 0, "result": None})
        + "\n"
    )
    persist_file.write_text(content)

    store = TaskStore(persist_path=str(persist_file))
    assert store.get("blank-1") is not None
    assert store.get("blank-2") is not None
