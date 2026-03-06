"""A2A HTTP Server — JSON-RPC 2.0 over HTTP with Agent Card.

Implements the Agent-to-Agent protocol v0.3.0 transport layer:
  - GET  /.well-known/agent.json  → Agent Card
  - POST /                        → JSON-RPC 2.0 (tasks/send, tasks/get, tasks/cancel)
  - POST / (sendSubscribe)        → SSE streaming

This server wraps the same CollaborationEngine used by the MCP tool,
allowing any A2A-compatible client to interact with modelmux agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from modelmux import __version__
from modelmux.a2a.engine import CollaborationEngine, EngineConfig
from modelmux.a2a.patterns import list_patterns
from modelmux.a2a.types import (
    AgentCard,
    CollaborationTask,
    Skill,
)

logger = logging.getLogger("modelmux.a2a.http")

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# A2A-specific error codes
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002


# ---------------------------------------------------------------------------
# Task Store — in-memory task tracking
# ---------------------------------------------------------------------------


@dataclass
class TaskEntry:
    """An active or completed collaboration task."""

    task_id: str
    context_id: str = ""
    state: str = "submitted"
    collab: CollaborationTask | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_event: asyncio.Event | None = None


class TaskStore:
    """In-memory task store with optional JSONL persistence.

    Completed/failed/canceled tasks are persisted to a JSONL file
    so they survive server restarts. Running tasks are not persisted
    (their async state cannot be serialized).
    """

    def __init__(
        self,
        max_tasks: int = 1000,
        persist_path: str = "",
    ) -> None:
        self._tasks: dict[str, TaskEntry] = {}
        self._max_tasks = max_tasks
        self._persist_path = persist_path
        if persist_path:
            self._load_from_disk()

    def create(self, task_id: str = "") -> TaskEntry:
        task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        entry = TaskEntry(
            task_id=task_id,
            context_id=f"ctx-{uuid.uuid4().hex[:8]}",
            cancel_event=asyncio.Event(),
        )
        self._tasks[task_id] = entry
        self._evict_old()
        return entry

    def get(self, task_id: str) -> TaskEntry | None:
        return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs: Any) -> TaskEntry | None:
        entry = self._tasks.get(task_id)
        if entry:
            for k, v in kwargs.items():
                if hasattr(entry, k):
                    setattr(entry, k, v)
            entry.updated_at = time.time()
            if entry.state in _TERMINAL_STATES:
                self._persist_entry(entry)
        return entry

    def _evict_old(self) -> None:
        if len(self._tasks) <= self._max_tasks:
            return
        completed = sorted(
            (
                (tid, e)
                for tid, e in self._tasks.items()
                if e.state in _TERMINAL_STATES
            ),
            key=lambda x: x[1].updated_at,
        )
        while len(self._tasks) > self._max_tasks and completed:
            tid, _ = completed.pop(0)
            del self._tasks[tid]

    def _persist_entry(self, entry: TaskEntry) -> None:
        """Append a terminal task entry to the JSONL file."""
        if not self._persist_path:
            return
        try:
            record = {
                "task_id": entry.task_id,
                "context_id": entry.context_id,
                "state": entry.state,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "result": entry.result,
            }
            with open(self._persist_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            logger.warning("Failed to persist task %s", entry.task_id)

    def _load_from_disk(self) -> None:
        """Load completed tasks from JSONL on startup."""
        import pathlib

        path = pathlib.Path(self._persist_path)
        if not path.exists():
            return
        try:
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                tid = record["task_id"]
                if tid in self._tasks:
                    continue
                self._tasks[tid] = TaskEntry(
                    task_id=tid,
                    context_id=record.get("context_id", ""),
                    state=record.get("state", "completed"),
                    result=record.get("result"),
                    created_at=record.get("created_at", 0),
                    updated_at=record.get("updated_at", 0),
                )
            logger.info(
                "Loaded %d tasks from %s", len(self._tasks), path
            )
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load tasks from %s", path)


_TERMINAL_STATES = {"completed", "failed", "canceled", "rejected"}


# ---------------------------------------------------------------------------
# A2A Server
# ---------------------------------------------------------------------------


class A2AServer:
    """A2A HTTP Server wrapping the modelmux collaboration engine."""

    def __init__(
        self,
        get_adapter: Any,  # Callable[[str], BaseAdapter]
        host: str = "0.0.0.0",
        port: int = 41520,
        workdir: str = ".",
        sandbox: str = "read-only",
        auth_token: str = "",
        persist_path: str = "",
    ) -> None:
        self._get_adapter = get_adapter
        self.host = host
        self.port = port
        self.workdir = workdir
        self.sandbox = sandbox
        self.auth_token = auth_token or os.environ.get("MODELMUX_A2A_TOKEN", "")
        self.store = TaskStore(persist_path=persist_path)
        self._agent_card: dict[str, Any] | None = None

    def build_agent_card(self) -> dict[str, Any]:
        """Build the Agent Card describing this server's capabilities."""
        if self._agent_card:
            return self._agent_card

        # Build skills from available patterns
        skills = []
        for name, info in list_patterns().items():
            skills.append(
                Skill(
                    id=f"collab_{name}",
                    name=f"{name} collaboration",
                    description=info["description"],
                    tags=["collaboration", name],
                    examples=[f"Run a {name} collaboration on: implement a REST API"],
                )
            )

        auth_schemes = ["bearer"] if self.auth_token else []

        card = AgentCard(
            name="modelmux",
            description=(
                "Multi-model collaboration orchestrator. "
                "Routes tasks to and coordinates between AI coding agents "
                "(Codex, Gemini, Claude, Ollama) with iterative feedback loops. "
                "Supports review, consensus, and debate collaboration patterns."
            ),
            url=f"http://{self.host}:{self.port}",
            version=__version__,
            protocol_version="0.3.0",
            skills=skills,
            capabilities={
                "streaming": True,
                "pushNotifications": False,
                "stateTransitionHistory": True,
            },
            auth_schemes=auth_schemes,
        )

        self._agent_card = card.to_dict()
        return self._agent_card

    # --- HTTP Handlers ---

    async def handle_agent_card(self, request: Request) -> JSONResponse:
        """GET /.well-known/agent.json"""
        return JSONResponse(self.build_agent_card())

    def _check_auth(self, request: Request) -> Response | None:
        """Validate Bearer token if authentication is configured.

        Returns an error response if auth fails, None if OK.
        """
        if not self.auth_token:
            return None  # No auth configured — open access

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {
                    "error": "Authentication required",
                    "hint": "Set Authorization: Bearer <token>",
                },
                status_code=401,
            )
        token = auth_header[7:]
        if not _constant_time_compare(token, self.auth_token):
            return JSONResponse(
                {"error": "Invalid token"},
                status_code=403,
            )
        return None

    async def handle_jsonrpc(self, request: Request) -> Response:
        """POST / — JSON-RPC 2.0 dispatcher."""
        # Auth check (Agent Card endpoint is always open per A2A spec)
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        try:
            body = await request.json()
        except Exception:
            return _jsonrpc_error(None, PARSE_ERROR, "Parse error")

        # Validate JSON-RPC structure
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            return _jsonrpc_error(
                body.get("id") if isinstance(body, dict) else None,
                INVALID_REQUEST,
                "Invalid JSON-RPC 2.0 request",
            )

        req_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params", {})

        # Route to handler
        handlers = {
            "tasks/send": self._handle_tasks_send,
            "tasks/get": self._handle_tasks_get,
            "tasks/cancel": self._handle_tasks_cancel,
            "tasks/sendSubscribe": self._handle_tasks_send_subscribe,
        }

        handler = handlers.get(method)
        if not handler:
            return _jsonrpc_error(req_id, METHOD_NOT_FOUND, f"Unknown method: {method}")

        try:
            result = await handler(params, request)
            # SSE responses are returned directly
            if isinstance(result, Response):
                return result
            return _jsonrpc_success(req_id, result)
        except TaskNotFoundError as e:
            return _jsonrpc_error(req_id, TASK_NOT_FOUND, str(e))
        except InvalidParamsError as e:
            return _jsonrpc_error(req_id, INVALID_PARAMS, str(e))
        except Exception:
            logger.exception("Internal error in %s (req_id=%s)", method, req_id)
            return _jsonrpc_error(req_id, INTERNAL_ERROR, "Internal server error")

    # --- JSON-RPC Method Handlers ---

    async def _handle_tasks_send(
        self, params: dict[str, Any], request: Request
    ) -> dict[str, Any]:
        """tasks/send — submit a task and wait for completion."""
        tp = _extract_task_params(params)

        # Create or resume task
        task_id = params.get("id", "")
        entry = self.store.get(task_id) if task_id else None
        if not entry:
            entry = self.store.create(task_id=task_id)

        entry.state = "working"
        self.store.update(entry.task_id, state="working")

        # Run collaboration (cancel_event allows tasks/cancel to stop it)
        engine = self._create_engine(
            cancel_event=entry.cancel_event,
            timeout_per_turn=tp.timeout_per_turn,
        )
        collab = await engine.run(
            task=tp.task_text,
            pattern_name=tp.pattern,
            providers=tp.provider_map,
            context_id=entry.context_id,
        )

        # Update store
        result = _collab_to_a2a_result(collab, entry)
        entry.collab = collab
        entry.result = result
        entry.state = collab.state.value
        self.store.update(entry.task_id, state=entry.state, result=result)

        return result

    async def _handle_tasks_get(
        self, params: dict[str, Any], request: Request
    ) -> dict[str, Any]:
        """tasks/get — retrieve current task state."""
        task_id = params.get("id", "")
        if not task_id:
            raise InvalidParamsError("Missing required parameter: id")

        entry = self.store.get(task_id)
        if not entry:
            raise TaskNotFoundError(f"Task not found: {task_id}")

        if entry.result:
            return entry.result

        return {
            "id": entry.task_id,
            "contextId": entry.context_id,
            "status": {"state": entry.state},
        }

    async def _handle_tasks_cancel(
        self, params: dict[str, Any], request: Request
    ) -> dict[str, Any]:
        """tasks/cancel — cancel a running task."""
        task_id = params.get("id", "")
        if not task_id:
            raise InvalidParamsError("Missing required parameter: id")

        entry = self.store.get(task_id)
        if not entry:
            raise TaskNotFoundError(f"Task not found: {task_id}")

        if entry.state in _TERMINAL_STATES:
            return {
                "id": entry.task_id,
                "contextId": entry.context_id,
                "status": {"state": entry.state},
            }

        # Signal cancellation
        if entry.cancel_event:
            entry.cancel_event.set()
        entry.state = "canceled"
        self.store.update(entry.task_id, state="canceled")

        return {
            "id": entry.task_id,
            "contextId": entry.context_id,
            "status": {"state": "canceled"},
        }

    async def _handle_tasks_send_subscribe(
        self, params: dict[str, Any], request: Request
    ) -> Response:
        """tasks/sendSubscribe — submit and stream updates via SSE."""
        from sse_starlette.sse import EventSourceResponse

        tp = _extract_task_params(params)

        task_id = params.get("id", "")
        entry = self.store.get(task_id) if task_id else None
        if not entry:
            entry = self.store.create(task_id=task_id)

        async def event_generator() -> AsyncGenerator[dict[str, str], None]:
            # Initial status event
            yield {
                "event": "task/status",
                "data": json.dumps(
                    {
                        "id": entry.task_id,
                        "contextId": entry.context_id,
                        "status": {"state": "working"},
                        "final": False,
                    }
                ),
            }

            entry.state = "working"
            self.store.update(entry.task_id, state="working")

            # Progress events
            progress_queue: asyncio.Queue[str] = asyncio.Queue()

            def on_progress(msg: str) -> None:
                try:
                    progress_queue.put_nowait(msg)
                except asyncio.QueueFull:
                    pass

            engine = self._create_engine(
                on_progress=on_progress,
                cancel_event=entry.cancel_event,
                timeout_per_turn=tp.timeout_per_turn,
            )

            # Run collaboration in background
            collab_future = asyncio.create_task(
                engine.run(
                    task=tp.task_text,
                    pattern_name=tp.pattern,
                    providers=tp.provider_map,
                    context_id=entry.context_id,
                )
            )

            try:
                # Stream progress events
                while not collab_future.done():
                    try:
                        msg = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                        yield {
                            "event": "task/progress",
                            "data": json.dumps(
                                {
                                    "id": entry.task_id,
                                    "status": {
                                        "state": "working",
                                        "message": msg,
                                    },
                                    "final": False,
                                }
                            ),
                        }
                    except asyncio.TimeoutError:
                        continue

                # Get final result
                collab = collab_future.result()
                result = _collab_to_a2a_result(collab, entry)
                entry.collab = collab
                entry.result = result
                entry.state = collab.state.value
                self.store.update(entry.task_id, state=entry.state, result=result)

                # Emit artifact events
                for art in collab.artifacts:
                    if art.metadata.get("type") == "trace":
                        continue
                    yield {
                        "event": "task/artifact",
                        "data": json.dumps(
                            {
                                "id": entry.task_id,
                                "artifact": {
                                    "artifactId": art.artifact_id,
                                    "name": art.name,
                                    "parts": [
                                        {"type": "text", "text": p.text}
                                        for p in art.parts
                                    ],
                                },
                                "final": False,
                            }
                        ),
                    }

                # Final status event
                yield {
                    "event": "task/status",
                    "data": json.dumps(
                        {
                            "id": entry.task_id,
                            "contextId": entry.context_id,
                            "status": {"state": collab.state.value},
                            "final": True,
                        }
                    ),
                }
            except asyncio.CancelledError:
                # Client disconnected — cancel the background task
                collab_future.cancel()
                entry.state = "canceled"
                self.store.update(entry.task_id, state="canceled")
                logger.info(
                    "SSE client disconnected, canceled task %s",
                    entry.task_id,
                )
                raise

        return EventSourceResponse(event_generator())

    # --- Helpers ---

    def _create_engine(
        self,
        on_progress: Any = None,
        cancel_event: asyncio.Event | None = None,
        timeout_per_turn: int = 0,
    ) -> CollaborationEngine:
        return CollaborationEngine(
            get_adapter=self._get_adapter,
            config=EngineConfig(
                workdir=self.workdir,
                sandbox=self.sandbox,
                timeout_per_turn=timeout_per_turn or 600,
                on_progress=on_progress,
                cancel_event=cancel_event,
            ),
        )

    async def handle_health(self, request: Request) -> JSONResponse:
        """GET /health — health check for load balancers."""
        return JSONResponse({"status": "ok", "version": __version__})

    def create_app(self) -> Starlette:
        """Build the Starlette ASGI application."""
        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware

        routes = [
            Route(
                "/.well-known/agent.json",
                self.handle_agent_card,
                methods=["GET"],
            ),
            Route("/health", self.handle_health, methods=["GET"]),
            Route("/", self.handle_jsonrpc, methods=["POST"]),
        ]
        middleware = [
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["GET", "POST"],
                allow_headers=["Authorization", "Content-Type"],
            ),
        ]
        return Starlette(routes=routes, middleware=middleware)

    def run(self) -> None:
        """Start the HTTP server (blocking)."""
        import uvicorn

        app = self.create_app()
        logger.info("A2A server starting on %s:%d", self.host, self.port)
        uvicorn.run(app, host=self.host, port=self.port, log_level="info")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TaskNotFoundError(Exception):
    pass


class InvalidParamsError(Exception):
    pass


def _constant_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to prevent timing attacks."""
    import hmac

    return hmac.compare_digest(a.encode(), b.encode())


@dataclass
class TaskParams:
    """Parsed parameters from a JSON-RPC task request."""

    task_text: str = ""
    pattern: str = "review"
    provider_map: dict[str, str] | None = None
    timeout_per_turn: int = 0  # 0 = use server default


def _extract_task_params(params: dict[str, Any]) -> TaskParams:
    """Extract task parameters from JSON-RPC params."""
    # Extract task text from A2A message format
    message = params.get("message", {})
    parts = message.get("parts", [])
    task_text = ""
    for part in parts:
        if part.get("type", "text") == "text":
            task_text += part.get("text", "")

    if not task_text:
        raise InvalidParamsError("No task text found in message.parts")

    # Extract from metadata
    metadata = params.get("metadata", {}) or message.get("metadata", {})
    pattern = metadata.get("pattern", "review")
    provider_map = metadata.get("providers")
    timeout_per_turn = int(metadata.get("timeout_per_turn", 0))

    return TaskParams(
        task_text=task_text,
        pattern=pattern,
        provider_map=provider_map,
        timeout_per_turn=timeout_per_turn,
    )


def _collab_to_a2a_result(
    collab: CollaborationTask, entry: TaskEntry
) -> dict[str, Any]:
    """Convert a CollaborationTask to A2A protocol result format."""
    result: dict[str, Any] = {
        "id": entry.task_id,
        "contextId": entry.context_id,
        "status": {
            "state": collab.state.value,
        },
    }

    # Build message history
    history = []
    for turn in collab.turns:
        history.append(
            {
                "role": "agent",
                "parts": [{"type": "text", "text": turn.output}],
                "metadata": {
                    "provider": turn.provider,
                    "collab_role": turn.role,
                    "duration_seconds": turn.duration_seconds,
                    "turn_id": turn.turn_id,
                },
            }
        )
    if history:
        result["history"] = history

    # Build artifacts
    artifacts = []
    for art in collab.artifacts:
        if art.metadata.get("type") == "trace":
            continue
        artifacts.append(
            {
                "artifactId": art.artifact_id,
                "name": art.name,
                "parts": [
                    {
                        "type": "text",
                        "text": p.text,
                        "mimeType": p.mime_type,
                    }
                    for p in art.parts
                ],
                "metadata": art.metadata,
            }
        )
    if artifacts:
        result["artifacts"] = artifacts

    # Include collaboration metadata
    result["metadata"] = {
        "pattern": collab.pattern,
        "rounds": collab.round_count,
        "duration_seconds": round(collab.elapsed_seconds, 1),
        "providers_used": collab.providers,
        "modelmux_task_id": collab.task_id,
    }

    return result


def _jsonrpc_success(req_id: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _jsonrpc_error(req_id: Any, code: int, message: str) -> JSONResponse:
    status = 200  # JSON-RPC errors use 200 status by convention
    if code == PARSE_ERROR or code == INVALID_REQUEST:
        status = 400
    return JSONResponse(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}},
        status_code=status,
    )
