"""Tests for the `modelmux dispatch` and `modelmux broadcast` CLI subcommands."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modelmux.adapters.base import AdapterResult, BaseAdapter


def _make_adapter(available=True, result=None):
    """Create a mock adapter that passes isinstance(x, BaseAdapter)."""
    mock = MagicMock(spec=BaseAdapter)
    mock.check_available.return_value = available
    if result is not None:
        mock.run = AsyncMock(return_value=result)
    return mock


def _dispatch_ns(**overrides):
    """Build a namespace for dispatch with sensible defaults."""
    ns = MagicMock()
    defaults = {
        "provider": "codex",
        "model": "",
        "sandbox": "read-only",
        "timeout": 300,
        "workdir": ".",
        "task": ["test"],
        "max_retries": 1,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(ns, k, v)
    return ns


def _broadcast_ns(**overrides):
    """Build a namespace for broadcast with sensible defaults."""
    ns = MagicMock()
    defaults = {
        "providers": None,
        "model": "",
        "sandbox": "read-only",
        "timeout": 300,
        "workdir": ".",
        "task": ["test"],
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(ns, k, v)
    return ns


# ── dispatch tests ──


def test_dispatch_no_task_exits(monkeypatch):
    """dispatch with no task and empty stdin should exit 1."""
    from modelmux.cli import _cmd_dispatch

    ns = _dispatch_ns(provider="auto", task=[])
    monkeypatch.setattr("sys.stdin", MagicMock(read=MagicMock(return_value="")))

    with pytest.raises(SystemExit) as exc_info:
        _cmd_dispatch(ns)
    assert exc_info.value.code == 1


def test_dispatch_no_providers_exits():
    from modelmux.cli import _cmd_dispatch

    ns = _dispatch_ns(provider="auto", task=["hello world"])
    mock_adapter = _make_adapter(available=False)

    with (
        patch(
            "modelmux.adapters.get_all_adapters",
            return_value={"codex": mock_adapter},
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cmd_dispatch(ns)
    assert exc_info.value.code == 1


def test_dispatch_success(capsys):
    from modelmux.cli import _cmd_dispatch

    ns = _dispatch_ns(task=["review", "this", "code"])
    fake_result = AdapterResult(
        run_id="abc123",
        provider="codex",
        status="success",
        output="Looks good!",
        summary="Looks good!",
    )
    mock_adapter = _make_adapter(available=True, result=fake_result)

    with patch(
        "modelmux.adapters.get_all_adapters",
        return_value={"codex": mock_adapter},
    ):
        _cmd_dispatch(ns)

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "success"
    assert result["provider"] == "codex"
    assert result["output"] == "Looks good!"


def test_dispatch_auto_routes(capsys):
    from modelmux.cli import _cmd_dispatch

    ns = _dispatch_ns(provider="auto", task=["analyze architecture"])
    mock_codex = _make_adapter(available=True)
    fake_result = AdapterResult(
        run_id="r1",
        provider="gemini",
        status="success",
        output="Analysis done",
        summary="Analysis done",
    )
    mock_gemini = _make_adapter(available=True, result=fake_result)

    with (
        patch(
            "modelmux.adapters.get_all_adapters",
            return_value={"codex": mock_codex, "gemini": mock_gemini},
        ),
        patch(
            "modelmux.routing.smart_route",
            return_value=("gemini", {}),
        ),
    ):
        _cmd_dispatch(ns)

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["provider"] == "gemini"


def test_dispatch_passes_model(capsys):
    from modelmux.cli import _cmd_dispatch

    ns = _dispatch_ns(
        model="gpt-5.4", timeout=120, workdir="/tmp", task=["test"]
    )
    fake_result = AdapterResult(
        run_id="r2", provider="codex", status="success", output="ok"
    )
    mock_adapter = _make_adapter(available=True, result=fake_result)

    with patch(
        "modelmux.adapters.get_all_adapters",
        return_value={"codex": mock_adapter},
    ):
        _cmd_dispatch(ns)

    call_kwargs = mock_adapter.run.call_args[1]
    assert call_kwargs["extra_args"] == {"model": "gpt-5.4"}
    assert call_kwargs["timeout"] == 120
    assert call_kwargs["workdir"] == "/tmp"


def test_dispatch_error_exits_1(capsys):
    from modelmux.cli import _cmd_dispatch

    ns = _dispatch_ns(task=["fail"])
    fake_result = AdapterResult(
        run_id="r3", provider="codex", status="error", error="broke"
    )
    mock_adapter = _make_adapter(available=True, result=fake_result)

    with (
        patch(
            "modelmux.adapters.get_all_adapters",
            return_value={"codex": mock_adapter},
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cmd_dispatch(ns)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "error"


def test_dispatch_retry_succeeds_on_second_attempt(capsys):
    """dispatch --max-retries=2 should retry on error."""
    from modelmux.cli import _cmd_dispatch

    ns = _dispatch_ns(max_retries=2, task=["retry me"])

    call_count = [0]
    error_result = AdapterResult(
        run_id="r4", provider="codex", status="error", error="transient"
    )
    ok_result = AdapterResult(
        run_id="r4", provider="codex", status="success", output="ok"
    )

    async def side_effect(**kwargs):
        call_count[0] += 1
        return error_result if call_count[0] == 1 else ok_result

    mock_adapter = _make_adapter(available=True)
    mock_adapter.run = AsyncMock(side_effect=side_effect)

    with (
        patch(
            "modelmux.adapters.get_all_adapters",
            return_value={"codex": mock_adapter},
        ),
        patch("time.sleep"),
    ):
        _cmd_dispatch(ns)

    assert call_count[0] == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "success"


# ── broadcast tests ──


def test_broadcast_success(capsys):
    """broadcast should return results from all providers."""
    from modelmux.cli import _cmd_broadcast

    ns = _broadcast_ns(task=["review code"])

    codex_result = AdapterResult(
        run_id="c1", provider="codex", status="success", output="LGTM"
    )
    gemini_result = AdapterResult(
        run_id="g1", provider="gemini", status="success", output="Fine"
    )
    mock_codex = _make_adapter(available=True, result=codex_result)
    mock_gemini = _make_adapter(available=True, result=gemini_result)

    with patch(
        "modelmux.adapters.get_all_adapters",
        return_value={"codex": mock_codex, "gemini": mock_gemini},
    ):
        _cmd_broadcast(ns)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data["results"]) == 2
    assert data["providers"] == ["codex", "gemini"]
    assert data["results"][0]["status"] == "success"
    assert data["results"][1]["status"] == "success"


def test_broadcast_specific_providers(capsys):
    """broadcast --providers codex should only use codex."""
    from modelmux.cli import _cmd_broadcast

    ns = _broadcast_ns(providers=["codex"], task=["test"])
    codex_result = AdapterResult(
        run_id="c1", provider="codex", status="success", output="ok"
    )
    mock_codex = _make_adapter(available=True, result=codex_result)
    mock_gemini = _make_adapter(available=True)

    with patch(
        "modelmux.adapters.get_all_adapters",
        return_value={"codex": mock_codex, "gemini": mock_gemini},
    ):
        _cmd_broadcast(ns)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["providers"] == ["codex"]
    assert len(data["results"]) == 1


def test_broadcast_all_fail_exits_1(capsys):
    """broadcast should exit 1 if all providers fail."""
    from modelmux.cli import _cmd_broadcast

    ns = _broadcast_ns(task=["fail"])
    err_result = AdapterResult(
        run_id="e1", provider="codex", status="error", error="nope"
    )
    mock_adapter = _make_adapter(available=True, result=err_result)

    with (
        patch(
            "modelmux.adapters.get_all_adapters",
            return_value={"codex": mock_adapter},
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cmd_broadcast(ns)

    assert exc_info.value.code == 1
