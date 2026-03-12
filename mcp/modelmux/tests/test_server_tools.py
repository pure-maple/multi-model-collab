"""Tests for server.py MCP tool functions.

Covers dispatch, broadcast, history, feedback, check, workflow, and collaborate.
"""

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modelmux.adapters.base import AdapterResult, BaseAdapter

# --- Fake Context for testing MCP tools ---


class FakeRequestContext:
    """Minimal request context stub."""


class FakeContext:
    """Mock MCP Context with async methods."""

    def __init__(self):
        self._request_context = FakeRequestContext()
        self.session = None
        self._messages = []

    async def info(self, msg):
        self._messages.append(("info", msg))

    async def warning(self, msg):
        self._messages.append(("warning", msg))


# --- Fake adapter for testing ---


class FakeAdapter(BaseAdapter):
    provider_name = "fake"

    def __init__(self, output="test output", status="success", error=""):
        self._output = output
        self._status = status
        self._error = error

    def _binary_name(self):
        return "fake"

    def check_available(self):
        return True

    def build_command(self, prompt, workdir, **kw):
        return ["echo", prompt]

    def parse_output(self, lines):
        return "\n".join(lines), "", ""

    async def run(self, prompt="", **kw):
        return AdapterResult(
            provider=self.provider_name,
            status=self._status,
            output=self._output,
            summary=self._output[:100],
            duration_seconds=1.5,
            error=self._error,
        )


class UnavailableAdapter(FakeAdapter):
    provider_name = "unavailable"

    def check_available(self):
        return False


@dataclass
class FakeDecomposeSubtask:
    name: str
    task: str
    provider: str = "auto"
    depends_on: list[str] | None = None

    def __post_init__(self):
        if self.depends_on is None:
            self.depends_on = []


class FakeDecomposePlan:
    def __init__(self, subtasks, waves, should_decompose=True):
        self.subtasks = subtasks
        self._waves = waves
        self.should_decompose = should_decompose

    def execution_order(self):
        return [[self.subtasks[idx] for idx in wave] for wave in self._waves]


# --- mux_dispatch tests ---


class TestMuxDispatch:
    @pytest.fixture(autouse=True)
    def _reset_loader(self):
        """Reset custom provider loader flag."""
        from modelmux.server import _ensure_custom_providers_loaded
        _ensure_custom_providers_loaded._done = False
        yield
        _ensure_custom_providers_loaded._done = False

    @pytest.mark.asyncio
    async def test_dispatch_success(self):
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        fake = FakeAdapter(output="hello world")

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", return_value=fake),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.log_dispatch"),
            patch("modelmux.server.log_result"),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_dispatch(
                provider="codex",
                task="hello",
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["status"] == "success"
            assert data["output"] == "hello world"

    @pytest.mark.asyncio
    async def test_dispatch_policy_blocked(self):
        from modelmux.server import mux_dispatch

        ctx = FakeContext()

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", return_value=FakeAdapter()),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=False, reason="rate limited")

            result = await mux_dispatch(
                provider="codex",
                task="hello",
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["status"] == "blocked"
            assert "rate limited" in data["error"]

    @pytest.mark.asyncio
    async def test_dispatch_cli_not_found_fallback(self):
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        unavail = UnavailableAdapter()
        fallback = FakeAdapter(output="fallback result")

        def mock_get_adapter(name):
            if name == "codex":
                return unavail
            return fallback

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", side_effect=mock_get_adapter),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.log_dispatch"),
            patch("modelmux.server.log_result"),
            patch("modelmux.server._get_fallback_candidates", return_value=["gemini"]),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_dispatch(
                provider="codex",
                task="hello",
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["status"] == "success"
            assert data["output"] == "fallback result"

    @pytest.mark.asyncio
    async def test_dispatch_no_cli_available(self):
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        unavail = UnavailableAdapter()

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", return_value=unavail),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server._get_fallback_candidates", return_value=[]),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_dispatch(
                provider="codex",
                task="hello",
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["status"] == "error"
            assert "not installed" in data["error"]

    @pytest.mark.asyncio
    async def test_dispatch_auto_route(self):
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        fake = FakeAdapter(output="auto routed")

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", return_value=fake),
            patch("modelmux.server.get_all_adapters", return_value={"codex": fake}),
            patch("modelmux.server._auto_route", return_value="codex"),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.log_dispatch"),
            patch("modelmux.server.log_result"),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_dispatch(
                provider="auto",
                task="hello",
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["status"] == "success"
            assert data["routed_from"] == "auto"

    @pytest.mark.asyncio
    async def test_dispatch_provider_model_syntax(self):
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        fake = FakeAdapter(output="model syntax")

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", return_value=fake),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.log_dispatch"),
            patch("modelmux.server.log_result"),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_dispatch(
                provider="dashscope/kimi-k2.5",
                task="hello",
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["status"] == "success"

    @pytest.mark.asyncio
    async def test_dispatch_failover(self):
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        failing = FakeAdapter(output="", status="error", error="cli crash")
        fallback = FakeAdapter(output="recovered")

        def mock_get_adapter(name):
            if name == "codex":
                return failing
            return fallback

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", side_effect=mock_get_adapter),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.log_dispatch"),
            patch("modelmux.server.log_result"),
            patch("modelmux.server._get_fallback_candidates", return_value=["gemini"]),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_dispatch(
                provider="codex",
                task="hello",
                ctx=ctx,
                failover=True,
            )
            data = json.loads(result)
            assert data["status"] == "success"
            assert data["failover_from"] == "codex"

    @pytest.mark.asyncio
    async def test_dispatch_returns_auto_decompose_result(self):
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        adapter = MagicMock()
        adapter.check_available.return_value = True
        adapter.run = AsyncMock()
        decompose_result = json.dumps(
            {
                "status": "success",
                "provider": "codex",
                "decomposed": True,
                "output": "merged plan",
            }
        )

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", return_value=adapter),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch(
                "modelmux.server._auto_decompose_task",
                return_value=decompose_result,
            ),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo

            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_dispatch(
                provider="codex",
                task="complex task",
                ctx=ctx,
                auto_decompose=True,
            )

        data = json.loads(result)
        assert data["decomposed"] is True
        adapter.run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dispatch_retries_same_provider_and_reports_progress(self):
        from modelmux.server import mux_dispatch

        ctx = FakeContext()
        adapter = MagicMock()
        adapter.check_available.return_value = True

        results = [
            AdapterResult(
                provider="codex",
                status="error",
                output="",
                summary="failed",
                duration_seconds=0.2,
                error="boom",
            ),
            AdapterResult(
                provider="codex",
                status="success",
                output="recovered",
                summary="recovered",
                duration_seconds=0.3,
            ),
        ]

        async def run_with_progress(**kwargs):
            kwargs["on_progress"]("streaming output")
            return results.pop(0)

        adapter.run = AsyncMock(side_effect=run_with_progress)

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", return_value=adapter),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server.write_status") as mock_write_status,
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.log_dispatch"),
            patch("modelmux.server.log_result"),
            patch(
                "modelmux.server.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo

            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_dispatch(
                provider="codex",
                task="retry task",
                ctx=ctx,
                max_retries=3,
                failover=False,
            )

        data = json.loads(result)
        assert data["status"] == "success"
        assert data["output"] == "recovered"
        assert adapter.run.await_count == 2
        mock_sleep.assert_awaited_once_with(2)
        assert mock_write_status.call_count >= 3
        assert (
            "info",
            "Attempt 2/3: retrying codex in 2s...",
        ) in ctx._messages


class TestAutoDecomposeTask:
    @pytest.mark.asyncio
    async def test_auto_decompose_task_returns_none_when_planner_fails(self):
        from modelmux.detect import CallerInfo
        from modelmux.server import _auto_decompose_task

        ctx = FakeContext()
        planner = MagicMock()
        planner.run = AsyncMock(
            return_value=AdapterResult(
                provider="planner",
                status="error",
                output="",
                summary="failed",
                duration_seconds=0.4,
                error="boom",
            )
        )

        with (
            patch("modelmux.server._get_adapter", return_value=planner),
            patch("modelmux.server._build_extra_args", return_value=([], {})),
        ):
            result = await _auto_decompose_task(
                task="investigate failure",
                planner_provider="planner",
                ctx=ctx,
                resolved_workdir="/tmp",
                sandbox="read-only",
                timeout=90,
                model="",
                profile="",
                profile_name="default",
                active_prof=None,
                caller=CallerInfo(client_name="test", provider="", platform=""),
                excluded=[],
            )

        assert result is None
        assert (
            "info",
            "Decomposition planner failed, falling back to direct dispatch",
        ) in ctx._messages

    @pytest.mark.asyncio
    async def test_auto_decompose_task_returns_none_when_plan_is_simple(self):
        from modelmux.detect import CallerInfo
        from modelmux.server import _auto_decompose_task

        ctx = FakeContext()
        planner = MagicMock()
        planner.run = AsyncMock(
            return_value=AdapterResult(
                provider="planner",
                status="success",
                output="simple",
                summary="simple",
                duration_seconds=0.5,
            )
        )
        plan = FakeDecomposePlan(subtasks=[], waves=[], should_decompose=False)

        with (
            patch("modelmux.server._get_adapter", return_value=planner),
            patch("modelmux.server._build_extra_args", return_value=([], {})),
            patch("modelmux.server.parse_decomposition", return_value=plan),
        ):
            result = await _auto_decompose_task(
                task="say hello",
                planner_provider="planner",
                ctx=ctx,
                resolved_workdir="/tmp",
                sandbox="read-only",
                timeout=90,
                model="",
                profile="",
                profile_name="default",
                active_prof=None,
                caller=CallerInfo(client_name="test", provider="", platform=""),
                excluded=[],
            )

        assert result is None
        assert ("info", "Task is simple enough — dispatching directly") in ctx._messages

    @pytest.mark.asyncio
    async def test_auto_decompose_task_uses_planner_for_unknown_provider(self):
        from modelmux.detect import CallerInfo
        from modelmux.server import _auto_decompose_task

        ctx = FakeContext()
        planner = MagicMock()
        planner.run = AsyncMock(
            side_effect=[
                AdapterResult(
                    provider="planner",
                    status="success",
                    output="plan",
                    summary="plan",
                    duration_seconds=0.4,
                ),
                AdapterResult(
                    provider="planner",
                    status="success",
                    output="unknown provider output",
                    summary="unknown provider output",
                    duration_seconds=0.6,
                ),
                AdapterResult(
                    provider="planner",
                    status="success",
                    output="merged output",
                    summary="merged output",
                    duration_seconds=0.5,
                ),
            ]
        )
        plan = FakeDecomposePlan(
            subtasks=[
                FakeDecomposeSubtask(
                    name="unknown",
                    task="use fallback provider",
                    provider="mystery",
                )
            ],
            waves=[[0]],
        )

        with (
            patch("modelmux.server._get_adapter", return_value=planner),
            patch(
                "modelmux.server.get_all_adapters",
                return_value={"planner": planner},
            ),
            patch("modelmux.server._build_extra_args", return_value=([], {})),
            patch("modelmux.server.parse_decomposition", return_value=plan),
            patch("modelmux.server.build_merge_prompt", return_value="merge"),
            patch("modelmux.server.log_result"),
        ):
            result = await _auto_decompose_task(
                task="fallback test",
                planner_provider="planner",
                ctx=ctx,
                resolved_workdir="/tmp",
                sandbox="write",
                timeout=90,
                model="",
                profile="",
                profile_name="default",
                active_prof=None,
                caller=CallerInfo(client_name="test", provider="", platform=""),
                excluded=[],
            )

        data = json.loads(result)
        assert data["status"] == "success"
        assert data["subtasks"][0]["provider"] == "planner"

    @pytest.mark.asyncio
    async def test_auto_decompose_task_executes_waves_and_merges_results(self):
        from modelmux.detect import CallerInfo
        from modelmux.server import _auto_decompose_task

        ctx = FakeContext()
        planner = MagicMock()
        planner.run = AsyncMock(
            side_effect=[
                AdapterResult(
                    provider="planner",
                    status="success",
                    output="plan",
                    summary="plan",
                    duration_seconds=0.5,
                ),
                AdapterResult(
                    provider="planner",
                    status="error",
                    output="",
                    summary="blocked",
                    duration_seconds=0.6,
                    error="denied",
                ),
                AdapterResult(
                    provider="planner",
                    status="success",
                    output="summary output",
                    summary="summary output",
                    duration_seconds=0.7,
                ),
                AdapterResult(
                    provider="planner",
                    status="success",
                    output="merged output",
                    summary="merged output",
                    duration_seconds=0.8,
                ),
            ]
        )
        available = MagicMock()
        available.check_available.return_value = True
        available.run = AsyncMock(
            return_value=AdapterResult(
                provider="alpha",
                status="success",
                output="alpha output",
                summary="alpha output",
                duration_seconds=0.4,
            )
        )
        unavailable = UnavailableAdapter()
        plan = FakeDecomposePlan(
            subtasks=[
                FakeDecomposeSubtask(
                    name="collect",
                    task="collect evidence",
                    provider="alpha",
                ),
                FakeDecomposeSubtask(
                    name="blocked",
                    task="blocked branch",
                    provider="blocked",
                ),
                FakeDecomposeSubtask(
                    name="summarize",
                    task="summarize findings",
                    provider="gemini",
                    depends_on=["collect"],
                ),
            ],
            waves=[[0, 1], [2]],
        )

        def get_adapter(name):
            mapping = {
                "planner": planner,
                "alpha": available,
                "gemini": unavailable,
                "blocked": MagicMock(),
            }
            return mapping[name]

        with (
            patch("modelmux.server._get_adapter", side_effect=get_adapter),
            patch(
                "modelmux.server.get_all_adapters",
                return_value={
                    "planner": planner,
                    "alpha": available,
                    "blocked": object(),
                    "gemini": unavailable,
                },
            ),
            patch(
                "modelmux.server._build_extra_args",
                return_value=(["--flag"], {"MODEL_PROFILE": "test"}),
            ),
            patch("modelmux.server.parse_decomposition", return_value=plan),
            patch(
                "modelmux.server.build_merge_prompt",
                return_value="merge collect + summarize",
            ) as mock_merge_prompt,
            patch("modelmux.server.log_result") as mock_log_result,
        ):
            result = await _auto_decompose_task(
                task="investigate regression",
                planner_provider="planner",
                ctx=ctx,
                resolved_workdir="/tmp/workdir",
                sandbox="write",
                timeout=180,
                model="gpt-5.4",
                profile="default",
                profile_name="default",
                active_prof=None,
                caller=CallerInfo(client_name="test", provider="", platform=""),
                excluded=["blocked"],
            )

        data = json.loads(result)
        assert data["decomposed"] is True
        assert [item["name"] for item in data["subtasks"]] == [
            "collect",
            "blocked",
            "summarize",
        ]
        assert data["subtasks"][1]["status"] == "error"
        assert data["output"] == "merged output"
        assert ("info", "Analyzing task for decomposition...") in ctx._messages
        assert (
            "info",
            "Wave 1: running 2 subtasks in parallel",
        ) in ctx._messages
        assert ("info", "Wave 2: summarize") in ctx._messages
        assert ("info", "Merging subtask results...") in ctx._messages
        assert available.run.await_args.kwargs["prompt"] == "collect evidence"
        summarize_prompt = planner.run.await_args_list[2].kwargs["prompt"]
        assert "Context from 'collect'" in summarize_prompt
        assert "alpha output" in summarize_prompt
        mock_merge_prompt.assert_called_once_with(
            "investigate regression",
            {
                "collect": "alpha output",
                "blocked": "",
                "summarize": "summary output",
            },
        )
        mock_log_result.assert_called_once()


# --- mux_broadcast tests ---


class TestMuxBroadcast:
    @pytest.fixture(autouse=True)
    def _reset_loader(self):
        from modelmux.server import _ensure_custom_providers_loaded
        _ensure_custom_providers_loaded._done = False
        yield
        _ensure_custom_providers_loaded._done = False

    @pytest.mark.asyncio
    async def test_broadcast_success(self):
        from modelmux.server import mux_broadcast

        ctx = FakeContext()
        fake_codex = FakeAdapter(output="codex result")
        fake_codex.provider_name = "codex"
        fake_gemini = FakeAdapter(output="gemini result")
        fake_gemini.provider_name = "gemini"

        def mock_get_adapter(name):
            if name == "codex":
                return fake_codex
            return fake_gemini

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", side_effect=mock_get_adapter),
            patch("modelmux.server.get_all_adapters", return_value={
                "codex": fake_codex, "gemini": fake_gemini,
            }),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.log_dispatch"),
            patch("modelmux.server.log_result"),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_broadcast(
                task="review code",
                ctx=ctx,
                providers=["codex", "gemini"],
            )
            data = json.loads(result)
            assert data["broadcast"] is True
            assert data["summary"]["total"] == 2
            assert data["summary"]["success"] == 2

    @pytest.mark.asyncio
    async def test_broadcast_no_providers(self):
        from modelmux.server import mux_broadcast

        ctx = FakeContext()

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server.get_all_adapters", return_value={}),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.count_recent", return_value=0),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )

            result = await mux_broadcast(
                task="review code",
                ctx=ctx,
                providers=[],
            )
            data = json.loads(result)
            assert data["status"] == "error"
            assert "No available" in data["error"]

    @pytest.mark.asyncio
    async def test_broadcast_with_compare(self):
        from modelmux.server import mux_broadcast

        ctx = FakeContext()
        fake = FakeAdapter(output="result")

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server._get_adapter", return_value=fake),
            patch("modelmux.server.get_all_adapters", return_value={"codex": fake}),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.log_dispatch"),
            patch("modelmux.server.log_result"),
            patch("modelmux.server.compare_results", return_value={"similarity": 1.0}),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_broadcast(
                task="compare",
                ctx=ctx,
                providers=["codex"],
                compare=True,
            )
            data = json.loads(result)
            assert "comparison" in data

    @pytest.mark.asyncio
    async def test_broadcast_policy_blocked(self):
        from modelmux.server import mux_broadcast

        ctx = FakeContext()
        fake = FakeAdapter()

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server.get_all_adapters", return_value={"codex": fake}),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform=""),
                [],
            )
            mock_check.return_value = MagicMock(allowed=False, reason="blocked")

            result = await mux_broadcast(
                task="review",
                ctx=ctx,
                providers=["codex"],
            )
            data = json.loads(result)
            assert data["status"] == "blocked"


# --- mux_history tests ---


class TestMuxHistory:
    @pytest.mark.asyncio
    async def test_history_entries(self):
        from modelmux.server import mux_history

        ctx = FakeContext()
        entries = [
            {"provider": "codex", "status": "success", "run_id": "abc"},
        ]

        with (
            patch("modelmux.server.read_history", return_value=entries),
        ):
            result = await mux_history(ctx=ctx, limit=10)
            data = json.loads(result)
            assert data["count"] == 1
            assert data["entries"][0]["run_id"] == "abc"

    @pytest.mark.asyncio
    async def test_history_stats_only(self):
        from modelmux.server import mux_history

        ctx = FakeContext()
        stats = {"total": 10, "success_rate": 0.9}

        with patch("modelmux.server.get_history_stats", return_value=stats):
            result = await mux_history(ctx=ctx, stats_only=True)
            data = json.loads(result)
            assert data["total"] == 10

    @pytest.mark.asyncio
    async def test_history_with_costs(self):
        from modelmux.server import mux_history

        ctx = FakeContext()
        entries = [{"provider": "codex", "status": "success"}]
        costs = {"total_usd": 0.05}

        with (
            patch("modelmux.server.read_history", return_value=entries),
            patch("modelmux.costs.aggregate_costs", return_value=costs),
        ):
            result = await mux_history(ctx=ctx, costs=True)
            data = json.loads(result)
            assert "costs" in data
            assert data["costs"]["total_usd"] == 0.05


# --- mux_feedback tests ---


class TestMuxFeedback:
    @pytest.mark.asyncio
    async def test_feedback_submit(self):
        from modelmux.server import mux_feedback

        ctx = FakeContext()

        with (
            patch("modelmux.feedback.log_feedback"),
            patch("modelmux.feedback.read_feedback", return_value=[]),
            patch("modelmux.server.read_history", return_value=[
                {"run_id": "abc", "provider": "codex", "task": "test task"},
            ]),
            patch("modelmux.routing.classify_task", return_value="analysis"),
        ):
            result = await mux_feedback(
                run_id="abc",
                rating=5,
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["status"] == "success"
            assert data["rating"] == 5
            assert data["provider"] == "codex"

    @pytest.mark.asyncio
    async def test_feedback_invalid_rating(self):
        from modelmux.server import mux_feedback

        ctx = FakeContext()

        result = await mux_feedback(
            run_id="abc",
            rating=0,
            ctx=ctx,
        )
        data = json.loads(result)
        assert data["status"] == "error"
        assert "1-5" in data["error"]

    @pytest.mark.asyncio
    async def test_feedback_list_recent(self):
        from modelmux.server import mux_feedback

        ctx = FakeContext()
        feedback_entries = [{"run_id": "x", "rating": 4}]

        with patch("modelmux.feedback.read_feedback", return_value=feedback_entries):
            result = await mux_feedback(
                run_id="",
                rating=1,
                ctx=ctx,
                list_recent=True,
            )
            data = json.loads(result)
            assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_feedback_provider_not_found(self):
        from modelmux.server import mux_feedback

        ctx = FakeContext()

        with (
            patch("modelmux.feedback.read_feedback", return_value=[]),
            patch("modelmux.server.read_history", return_value=[]),
        ):
            result = await mux_feedback(
                run_id="missing",
                rating=3,
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["status"] == "error"
            assert "provider" in data["error"].lower()


# --- mux_check tests ---


class TestMuxCheck:
    @pytest.fixture(autouse=True)
    def _reset_loader(self):
        from modelmux.server import _ensure_custom_providers_loaded
        _ensure_custom_providers_loaded._done = False
        yield
        _ensure_custom_providers_loaded._done = False

    @pytest.mark.asyncio
    async def test_check_basic(self):
        from modelmux.server import mux_check

        ctx = FakeContext()
        fake = FakeAdapter()

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server.get_all_adapters", return_value={"fake": fake}),
            patch("modelmux.server._provider_health_summary", return_value={}),
            patch("modelmux.server.load_policy") as mock_policy,
            patch("modelmux.server.list_active", return_value=[]),
            patch("modelmux.server.get_audit_stats", return_value={}),
            patch("modelmux.routing._BENCHMARK_FILE") as mock_bf,
            patch("modelmux.feedback._feedback_file") as mock_ff,
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform="test"),
                [],
            )
            mock_policy.return_value = MagicMock(
                allowed_providers=[],
                blocked_providers=[],
                blocked_sandboxes=[],
                max_timeout=0,
                max_calls_per_hour=0,
                max_calls_per_day=0,
            )
            mock_bf.exists.return_value = False
            mock_ff.return_value = MagicMock(exists=MagicMock(return_value=False))

            result = await mux_check(ctx=ctx)
            data = json.loads(result)
            assert "fake" in data
            assert data["fake"]["available"] is True
            assert "_caller" in data
            assert "_config" in data
            assert "_policy" in data
            assert "_routing" in data

    @pytest.mark.asyncio
    async def test_check_with_diagnose(self):
        from modelmux.server import mux_check

        ctx = FakeContext()
        fake = FakeAdapter()

        @dataclass
        class FakeScore:
            keyword_score: float = 0.5
            success_rate: float = 0.8
            latency_score: float = 0.3
            benchmark_score: float = 0.6
            feedback_score: float = 0.4
            composite: float = 0.55
            history_calls: int = 10

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_config") as mock_config,
            patch("modelmux.server._detect_and_build_exclusions") as mock_detect,
            patch("modelmux.server.get_all_adapters", return_value={"fake": fake}),
            patch("modelmux.server._provider_health_summary", return_value={}),
            patch("modelmux.server.load_policy") as mock_policy,
            patch("modelmux.server.list_active", return_value=[]),
            patch("modelmux.server.get_audit_stats", return_value={}),
            patch("modelmux.routing._BENCHMARK_FILE") as mock_bf,
            patch("modelmux.feedback._feedback_file") as mock_ff,
            patch("modelmux.server.route_by_rules", return_value=None),
            patch(
                "modelmux.routing.smart_route",
                return_value=("fake", {"fake": FakeScore()}),
            ),
            patch("modelmux.routing.classify_task", return_value="analysis"),
        ):
            mock_config.return_value = MagicMock(
                active_profile="default",
                profiles={},
                disabled_providers=[],
                routing_rules=[],
                default_provider="codex",
                auto_exclude_caller=True,
                caller_override="",
            )
            from modelmux.detect import CallerInfo
            mock_detect.return_value = (
                CallerInfo(client_name="test", provider="", platform="test"),
                [],
            )
            mock_policy.return_value = MagicMock(
                allowed_providers=[],
                blocked_providers=[],
                blocked_sandboxes=[],
                max_timeout=0,
                max_calls_per_hour=0,
                max_calls_per_day=0,
            )
            mock_bf.exists.return_value = True
            mock_ff.return_value = MagicMock(exists=MagicMock(return_value=True))

            result = await mux_check(ctx=ctx, diagnose="analyze security")
            data = json.loads(result)
            assert "_diagnose" in data
            assert data["_diagnose"]["category"] == "analysis"
            assert "fake" in data["_diagnose"]["scores"]


# --- mux_workflow tests ---


class TestMuxWorkflow:
    @pytest.mark.asyncio
    async def test_workflow_list(self):
        from modelmux.server import mux_workflow

        ctx = FakeContext()

        with (
            patch("modelmux.config._find_config_file", return_value=None),
        ):
            result = await mux_workflow(
                workflow="",
                task="",
                ctx=ctx,
                list_workflows=True,
            )
            data = json.loads(result)
            assert "review" in data or "consensus" in data

    @pytest.mark.asyncio
    async def test_workflow_unknown(self):
        from modelmux.server import mux_workflow

        ctx = FakeContext()

        with (
            patch("modelmux.config._find_config_file", return_value=None),
            patch("modelmux.server.load_policy") as mock_policy,
            patch("modelmux.server.count_recent", return_value=0),
        ):
            mock_policy.return_value = MagicMock()

            result = await mux_workflow(
                workflow="nonexistent",
                task="test",
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["status"] == "error"
            assert "Unknown workflow" in data["error"]

    @pytest.mark.asyncio
    async def test_workflow_execution(self):
        from modelmux.server import mux_workflow

        ctx = FakeContext()
        fake = FakeAdapter(output="step result")

        with (
            patch("modelmux.config._find_config_file", return_value=None),
            patch("modelmux.server._get_adapter", return_value=fake),
            patch("modelmux.server.load_policy") as mock_policy,
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.server.write_status"),
            patch("modelmux.server.remove_status"),
            patch("modelmux.server.log_dispatch"),
            patch("modelmux.server.log_result"),
        ):
            mock_policy.return_value = MagicMock()
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_workflow(
                workflow="review",
                task="review my code",
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["workflow"] == "review"
            assert "steps" in data
            assert "summary" in data


# --- mux_collaborate tests ---


class TestMuxCollaborate:
    @pytest.fixture(autouse=True)
    def _reset_loader(self):
        from modelmux.server import _ensure_custom_providers_loaded
        _ensure_custom_providers_loaded._done = False
        yield
        _ensure_custom_providers_loaded._done = False

    @pytest.mark.asyncio
    async def test_collaborate_list_patterns(self):
        from modelmux.server import mux_collaborate

        ctx = FakeContext()

        result = await mux_collaborate(
            task="",
            pattern="",
            ctx=ctx,
            list_patterns=True,
        )
        data = json.loads(result)
        assert isinstance(data, dict)
        assert "review" in data or len(data) > 0

    @pytest.mark.asyncio
    async def test_collaborate_invalid_json_providers(self):
        from modelmux.server import mux_collaborate

        ctx = FakeContext()

        with patch("modelmux.server._ensure_custom_providers_loaded"):
            result = await mux_collaborate(
                task="test",
                pattern="review",
                ctx=ctx,
                providers="not json",
            )
            data = json.loads(result)
            assert data["status"] == "error"
            assert "Invalid providers JSON" in data["error"]

    @pytest.mark.asyncio
    async def test_collaborate_policy_blocked(self):
        from modelmux.server import mux_collaborate

        ctx = FakeContext()

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
        ):
            mock_check.return_value = MagicMock(allowed=False, reason="blocked")

            result = await mux_collaborate(
                task="test",
                pattern="review",
                ctx=ctx,
                providers='{"implementer": "codex", "reviewer": "gemini"}',
            )
            data = json.loads(result)
            assert data["status"] == "blocked"

    @pytest.mark.asyncio
    async def test_collaborate_success_uses_pattern_defaults_and_filters_trace(
        self,
    ):
        from modelmux.server import mux_collaborate

        ctx = FakeContext()
        pattern = SimpleNamespace(
            roles={
                "implementer": SimpleNamespace(preferred_provider="codex"),
                "reviewer": SimpleNamespace(preferred_provider="gemini"),
            }
        )

        class FakeEngine:
            def __init__(self, get_adapter, config):
                self.get_adapter = get_adapter
                self.config = config

            async def run(
                self,
                task,
                pattern_name,
                providers,
                max_rounds,
                max_wall_time,
            ):
                self.config.on_progress("round 1")
                await asyncio.sleep(0)
                return SimpleNamespace(
                    task_id="task-1",
                    context_id="ctx-1",
                    pattern=pattern_name,
                    state=SimpleNamespace(value="completed"),
                    round_count=2,
                    elapsed_seconds=4.2,
                    providers=["codex", "gemini"],
                    turns=[
                        SimpleNamespace(
                            turn_id="t1",
                            role="implementer",
                            provider="codex",
                            status="success",
                            duration_seconds=1.2,
                            output_summary="",
                            output="implementer full output",
                        ),
                        SimpleNamespace(
                            turn_id="t2",
                            role="reviewer",
                            provider="gemini",
                            status="error",
                            duration_seconds=0.8,
                            output_summary="review failed",
                            output="review failed details",
                        ),
                    ],
                    artifacts=[
                        SimpleNamespace(
                            artifact_id="trace-1",
                            name="trace",
                            parts=[SimpleNamespace(text="debug trace")],
                            metadata={"type": "trace"},
                        ),
                        SimpleNamespace(
                            artifact_id="artifact-1",
                            name="summary",
                            parts=[
                                SimpleNamespace(text="hello"),
                                SimpleNamespace(text=" world"),
                            ],
                            metadata={"type": "summary"},
                        ),
                    ],
                )

        with (
            patch("modelmux.server._ensure_custom_providers_loaded"),
            patch("modelmux.server.load_policy"),
            patch("modelmux.server.check_policy") as mock_check,
            patch("modelmux.server.count_recent", return_value=0),
            patch("modelmux.a2a.patterns.get_pattern", return_value=pattern),
            patch("modelmux.server.CollaborationEngine", FakeEngine),
            patch("modelmux.server.log_result") as mock_log_result,
        ):
            mock_check.return_value = MagicMock(allowed=True)

            result = await mux_collaborate(
                task="review the branch",
                pattern="review",
                ctx=ctx,
                workdir=".",
                sandbox="read-only",
                timeout=90,
            )

        data = json.loads(result)
        assert data["state"] == "completed"
        assert data["providers_used"] == ["codex", "gemini"]
        assert data["final_output"] == "implementer full output"
        assert data["turns"][0]["output_summary"] == "implementer full output"
        assert data["turns"][1]["output_summary"] == "review failed"
        assert data["artifacts"] == [
            {
                "id": "artifact-1",
                "name": "summary",
                "content": "hello world",
            }
        ]
        assert ("info", "Starting 'review' collaboration...") in ctx._messages
        assert ("info", "round 1") in ctx._messages
        assert mock_check.call_count == 2
        mock_log_result.assert_called_once()


# --- _detect_and_build_exclusions tests ---


class TestDetectAndBuildExclusions:
    def test_with_auto_exclude(self):
        from modelmux.server import _detect_and_build_exclusions

        ctx = FakeContext()
        config = MagicMock(
            disabled_providers=["ollama"],
            auto_exclude_caller=True,
            caller_override="",
        )

        with (
            patch("modelmux.server.detect_caller") as mock_detect,
            patch("modelmux.server.get_excluded_providers", return_value=["claude"]),
        ):
            mock_detect.return_value = MagicMock(
                client_name="claude-code",
                provider="claude",
                platform="claude",
            )
            caller, excluded = _detect_and_build_exclusions(ctx, config)
            assert "ollama" in excluded
            assert "claude" in excluded

    def test_without_auto_exclude(self):
        from modelmux.server import _detect_and_build_exclusions

        ctx = FakeContext()
        config = MagicMock(
            disabled_providers=["ollama"],
            auto_exclude_caller=False,
            caller_override="",
        )

        with (
            patch("modelmux.server.detect_caller") as mock_detect,
            patch("modelmux.server.get_excluded_providers", return_value=["claude"]),
        ):
            mock_detect.return_value = MagicMock(
                client_name="claude-code",
                provider="claude",
                platform="claude",
            )
            caller, excluded = _detect_and_build_exclusions(ctx, config)
            assert "ollama" in excluded
            assert "claude" not in excluded


# --- _ensure_custom_providers_loaded tests ---


class TestEnsureCustomProvidersLoaded:
    def setup_method(self):
        from modelmux.server import _ensure_custom_providers_loaded
        _ensure_custom_providers_loaded._done = False

    def teardown_method(self):
        from modelmux.server import _ensure_custom_providers_loaded
        _ensure_custom_providers_loaded._done = False

    def test_loads_once(self):
        from modelmux.server import _ensure_custom_providers_loaded

        with (
            patch("modelmux.config._find_config_file", return_value=None),
        ):
            _ensure_custom_providers_loaded()
            assert _ensure_custom_providers_loaded._done is True
            # Call again — should not re-execute
            _ensure_custom_providers_loaded()

    def test_loads_config_file(self):
        from modelmux.server import _ensure_custom_providers_loaded

        mock_file = MagicMock()
        with (
            patch("modelmux.config._find_config_file", return_value=mock_file),
            patch("modelmux.config._load_file", return_value={}),
            patch("modelmux.server.load_custom_providers") as mock_load,
        ):
            _ensure_custom_providers_loaded()
            assert mock_load.called
