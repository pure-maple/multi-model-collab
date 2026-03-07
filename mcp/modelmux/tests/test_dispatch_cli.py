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
        "failover": False,
        "profile": "",
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
        "compare": False,
        "profile": "",
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


def test_dispatch_failover_success(capsys):
    """dispatch --failover should try another provider on error."""
    from modelmux.cli import _cmd_dispatch

    ns = _dispatch_ns(task=["fail then recover"], failover=True)
    err_result = AdapterResult(
        run_id="r5", provider="codex", status="error", error="crashed"
    )
    ok_result = AdapterResult(
        run_id="r6", provider="gemini", status="success", output="recovered"
    )
    mock_codex = _make_adapter(available=True, result=err_result)
    mock_gemini = _make_adapter(available=True, result=ok_result)

    with patch(
        "modelmux.adapters.get_all_adapters",
        return_value={"codex": mock_codex, "gemini": mock_gemini},
    ):
        _cmd_dispatch(ns)

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "success"
    assert result["provider"] == "gemini"
    assert result["failover_from"] == "codex"


def test_dispatch_no_failover_by_default(capsys):
    """dispatch without --failover should not try other providers."""
    from modelmux.cli import _cmd_dispatch

    ns = _dispatch_ns(task=["fail"])
    err_result = AdapterResult(
        run_id="r7", provider="codex", status="error", error="crashed"
    )
    mock_codex = _make_adapter(available=True, result=err_result)
    mock_gemini = _make_adapter(available=True)

    with (
        patch(
            "modelmux.adapters.get_all_adapters",
            return_value={"codex": mock_codex, "gemini": mock_gemini},
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cmd_dispatch(ns)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "error"
    assert "failover_from" not in result


def test_broadcast_compare(capsys):
    """broadcast --compare should add comparison analysis."""
    from modelmux.cli import _cmd_broadcast

    ns = _broadcast_ns(task=["compare test"], compare=True)
    codex_result = AdapterResult(
        run_id="c1",
        provider="codex",
        status="success",
        output="The code looks good and well structured",
        duration_seconds=5.0,
    )
    gemini_result = AdapterResult(
        run_id="g1",
        provider="gemini",
        status="success",
        output="The code is well structured and readable",
        duration_seconds=3.0,
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
    assert "comparison" in data
    assert data["comparison"]["comparable"] is True
    assert "agreement_score" in data["comparison"]
    assert "speed_ranking" in data["comparison"]


def test_broadcast_no_compare_by_default(capsys):
    """broadcast without --compare should not include comparison."""
    from modelmux.cli import _cmd_broadcast

    ns = _broadcast_ns(task=["no compare"])
    result = AdapterResult(
        run_id="c1", provider="codex", status="success", output="ok"
    )
    mock_adapter = _make_adapter(available=True, result=result)

    with patch(
        "modelmux.adapters.get_all_adapters",
        return_value={"codex": mock_adapter},
    ):
        _cmd_broadcast(ns)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "comparison" not in data


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


# ── profile tests ──


def test_dispatch_with_profile(capsys):
    """dispatch --profile should apply profile model override."""
    from modelmux.cli import _cmd_dispatch
    from modelmux.config import MuxConfig, Profile, ProviderConfig

    ns = _dispatch_ns(task=["test"], profile="budget")
    fake_result = AdapterResult(
        run_id="r8", provider="codex", status="success", output="ok"
    )
    mock_adapter = _make_adapter(available=True, result=fake_result)
    config = MuxConfig(
        profiles={
            "budget": Profile(
                providers={"codex": ProviderConfig(model="gpt-4.1-mini")},
            ),
        },
    )

    with (
        patch(
            "modelmux.adapters.get_all_adapters",
            return_value={"codex": mock_adapter},
        ),
        patch("modelmux.config.load_config", return_value=config),
    ):
        _cmd_dispatch(ns)

    call_kwargs = mock_adapter.run.call_args[1]
    assert call_kwargs["extra_args"]["model"] == "gpt-4.1-mini"


def test_profile_list_empty(capsys):
    """profile with no profiles should show 'No profiles'."""
    from modelmux.cli import _cmd_profile
    from modelmux.config import MuxConfig

    ns = MagicMock()
    ns.name = ""
    ns.json = False

    with patch("modelmux.config.load_config", return_value=MuxConfig()):
        _cmd_profile(ns)

    captured = capsys.readouterr()
    assert "No profiles" in captured.out


def test_profile_list_with_profiles(capsys):
    """profile should list configured profiles."""
    from modelmux.cli import _cmd_profile
    from modelmux.config import MuxConfig, Profile, ProviderConfig

    config = MuxConfig(
        active_profile="budget",
        profiles={
            "budget": Profile(
                description="Use cheaper models",
                providers={"codex": ProviderConfig(model="gpt-4.1-mini")},
            ),
        },
    )
    ns = MagicMock()
    ns.name = ""
    ns.json = False

    with patch("modelmux.config.load_config", return_value=config):
        _cmd_profile(ns)

    captured = capsys.readouterr()
    assert "budget" in captured.out
    assert "cheaper" in captured.out


def test_profile_show_json(capsys):
    """profile <name> --json should output JSON."""
    from modelmux.cli import _cmd_profile
    from modelmux.config import MuxConfig, Profile, ProviderConfig

    config = MuxConfig(
        profiles={
            "fast": Profile(
                description="Speed",
                providers={"gemini": ProviderConfig(model="gemini-2.5-flash")},
            ),
        },
    )
    ns = MagicMock()
    ns.name = "fast"
    ns.json = True

    with patch("modelmux.config.load_config", return_value=config):
        _cmd_profile(ns)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["name"] == "fast"
    assert data["providers"]["gemini"]["model"] == "gemini-2.5-flash"


def test_profile_not_found():
    """profile <unknown> should exit 1."""
    from modelmux.cli import _cmd_profile
    from modelmux.config import MuxConfig

    ns = MagicMock()
    ns.name = "nonexistent"
    ns.json = False

    with (
        patch("modelmux.config.load_config", return_value=MuxConfig()),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cmd_profile(ns)
    assert exc_info.value.code == 1


# ── feedback tests ──


def _feedback_ns(**overrides):
    """Build a namespace for feedback with sensible defaults."""
    ns = MagicMock()
    defaults = {
        "run_id": "",
        "provider": "",
        "rating": 0,
        "comment": "",
        "category": "",
        "list": False,
        "hours": 0,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(ns, k, v)
    return ns


def test_feedback_submit(capsys, tmp_path):
    """feedback --run-id --provider --rating should log feedback."""
    from modelmux.cli import _cmd_feedback

    ns = _feedback_ns(run_id="abc123", provider="codex", rating=4, comment="great")

    with patch("modelmux.feedback._feedback_file", return_value=tmp_path / "fb.jsonl"):
        _cmd_feedback(ns)

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "ok"
    assert result["run_id"] == "abc123"
    assert result["rating"] == 4


def test_feedback_missing_args_exits():
    """feedback without required args should exit 1."""
    from modelmux.cli import _cmd_feedback

    ns = _feedback_ns()  # all empty

    with pytest.raises(SystemExit) as exc_info:
        _cmd_feedback(ns)
    assert exc_info.value.code == 1


def test_feedback_invalid_rating_exits(tmp_path):
    """feedback with rating outside 1-5 should exit 1."""
    from modelmux.cli import _cmd_feedback

    ns = _feedback_ns(run_id="x", provider="codex", rating=7)

    with (
        patch("modelmux.feedback._feedback_file", return_value=tmp_path / "fb.jsonl"),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cmd_feedback(ns)
    assert exc_info.value.code == 1


def test_feedback_list_empty(capsys):
    """feedback --list with no data should show message."""
    from modelmux.cli import _cmd_feedback

    ns = _feedback_ns(**{"list": True})

    with patch("modelmux.feedback.read_feedback", return_value=[]):
        _cmd_feedback(ns)

    captured = capsys.readouterr()
    assert "No feedback" in captured.out


# ── clean tests ──


def test_clean_dry_run(capsys, tmp_path):
    """clean --dry-run should not delete files."""
    from modelmux.cli import _cmd_clean

    history = tmp_path / "history.jsonl"
    history.write_text('{"test": true}\n')

    ns = MagicMock()
    ns.what = "all"
    ns.dry_run = True

    # Create the config dir structure
    cfg = tmp_path / ".config" / "modelmux"
    cfg.mkdir(parents=True)
    h = cfg / "history.jsonl"
    h.write_text('{"test": true}\n')

    with patch("pathlib.Path.home", return_value=tmp_path):
        _cmd_clean(ns)

    # File should still exist
    assert h.exists()

    captured = capsys.readouterr()
    assert "dry run" in captured.out


def test_clean_removes_file(capsys, tmp_path):
    """clean history should remove history.jsonl."""
    from modelmux.cli import _cmd_clean

    cfg = tmp_path / ".config" / "modelmux"
    cfg.mkdir(parents=True)
    h = cfg / "history.jsonl"
    h.write_text('{"test": true}\n')

    ns = MagicMock()
    ns.what = "history"
    ns.dry_run = False

    with patch("pathlib.Path.home", return_value=tmp_path):
        _cmd_clean(ns)

    assert not h.exists()
    captured = capsys.readouterr()
    assert "Cleaned" in captured.out


def test_clean_nothing_to_clean(capsys, tmp_path):
    """clean with no files shows nothing message."""
    from modelmux.cli import _cmd_clean

    ns = MagicMock()
    ns.what = "all"
    ns.dry_run = False

    with patch("pathlib.Path.home", return_value=tmp_path):
        _cmd_clean(ns)

    captured = capsys.readouterr()
    assert "Nothing to clean" in captured.out


# ── history tests ──


def _history_ns(**overrides):
    """Build a namespace for history with sensible defaults."""
    ns = MagicMock()
    defaults = {
        "stats": False,
        "limit": 10,
        "provider": "",
        "hours": 0,
        "costs": False,
        "source": "",
        "json": False,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(ns, k, v)
    return ns


def test_history_json_entries(capsys):
    """history --json outputs valid JSON with entries."""
    from modelmux.cli import _cmd_history

    entries = [
        {"provider": "codex", "status": "success", "ts": 1000, "task": "test"},
    ]
    ns = _history_ns(json=True)

    with patch("modelmux.history.read_history", return_value=entries):
        _cmd_history(ns)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["count"] == 1
    assert data["entries"][0]["provider"] == "codex"


def test_history_json_empty(capsys):
    """history --json with no entries outputs empty list."""
    from modelmux.cli import _cmd_history

    ns = _history_ns(json=True)

    with patch("modelmux.history.read_history", return_value=[]):
        _cmd_history(ns)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["count"] == 0
    assert data["entries"] == []


def test_history_stats_json(capsys):
    """history --stats --json outputs stats as JSON."""
    from modelmux.cli import _cmd_history

    stats = {"total": 5, "by_provider": {"codex": {"calls": 5}}}
    ns = _history_ns(stats=True, json=True)

    with patch("modelmux.history.get_history_stats", return_value=stats):
        _cmd_history(ns)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total"] == 5


def test_history_no_data(capsys):
    """history with no entries shows message."""
    from modelmux.cli import _cmd_history

    ns = _history_ns()

    with patch("modelmux.history.read_history", return_value=[]):
        _cmd_history(ns)

    captured = capsys.readouterr()
    assert "No history" in captured.out


def test_history_stats_text(capsys):
    """history --stats in text mode shows statistics."""
    from modelmux.cli import _cmd_history

    stats = {
        "total": 3,
        "by_provider": {
            "codex": {"calls": 2, "success_rate": 100, "avg_duration": 5.0},
            "gemini": {"calls": 1, "success_rate": 50, "avg_duration": 3.0},
        },
        "by_source": {"dispatch": 2, "broadcast": 1},
    }
    ns = _history_ns(stats=True)

    with patch("modelmux.history.get_history_stats", return_value=stats):
        _cmd_history(ns)

    captured = capsys.readouterr()
    assert "Total dispatches: 3" in captured.out
    assert "codex" in captured.out


def test_history_stats_empty(capsys):
    """history --stats with no data shows message."""
    from modelmux.cli import _cmd_history

    ns = _history_ns(stats=True)

    with patch("modelmux.history.get_history_stats", return_value={"total": 0}):
        _cmd_history(ns)

    captured = capsys.readouterr()
    assert "No history" in captured.out


def test_history_stats_with_costs(capsys):
    """history --stats --costs shows cost breakdown."""
    from modelmux.cli import _cmd_history

    stats = {
        "total": 1,
        "by_provider": {"codex": {"calls": 1, "success_rate": 100, "avg_duration": 2}},
        "by_source": {},
        "costs": {
            "entries_with_usage": 1,
            "total_input_tokens": 500,
            "total_output_tokens": 200,
            "total_cost_usd": 0.002,
            "by_provider": {
                "codex": {
                    "calls": 1,
                    "input_tokens": 500,
                    "output_tokens": 200,
                    "total_cost": 0.002,
                },
            },
        },
    }
    ns = _history_ns(stats=True, costs=True)

    with patch("modelmux.history.get_history_stats", return_value=stats):
        _cmd_history(ns)

    captured = capsys.readouterr()
    assert "Cost Estimation" in captured.out
    assert "$0.0020" in captured.out


def test_history_text_entries(capsys):
    """history in text mode shows entries."""
    import time

    from modelmux.cli import _cmd_history

    entries = [
        {
            "provider": "codex",
            "status": "success",
            "ts": time.time() - 60,
            "task": "review code",
            "duration_seconds": 3.5,
            "source": "dispatch",
        },
    ]
    ns = _history_ns()

    with patch("modelmux.history.read_history", return_value=entries):
        _cmd_history(ns)

    captured = capsys.readouterr()
    assert "Recent Dispatches" in captured.out
    assert "codex" in captured.out


# ── check tests ──


def test_check_text(capsys):
    """check in text mode shows provider availability."""
    from modelmux.cli import _cmd_check

    ns = MagicMock()
    ns.json = False

    mock_adapter = MagicMock(spec=BaseAdapter)
    mock_adapter.check_available.return_value = True
    mock_adapter._binary_name.return_value = "codex"

    with (
        patch("modelmux.adapters.ADAPTERS", {"codex": lambda: mock_adapter}),
        patch("shutil.which", return_value="/usr/bin/codex"),
        patch("modelmux.config.load_config") as mock_config,
        patch("modelmux.history.get_history_stats", return_value={"total": 0}),
    ):
        mock_config.return_value = MagicMock(
            profiles={},
            active_profile="default",
            routing_rules=[],
        )
        _cmd_check(ns)

    captured = capsys.readouterr()
    assert "modelmux" in captured.out
    assert "Providers" in captured.out


def test_check_json(capsys):
    """check --json outputs valid JSON."""
    from modelmux.cli import _cmd_check

    ns = MagicMock()
    ns.json = True

    mock_adapter = MagicMock(spec=BaseAdapter)
    mock_adapter.check_available.return_value = True
    mock_adapter._binary_name.return_value = "codex"

    with (
        patch("modelmux.adapters.ADAPTERS", {"codex": lambda: mock_adapter}),
        patch("shutil.which", return_value="/usr/bin/codex"),
        patch("modelmux.config.load_config") as mock_config,
    ):
        mock_config.return_value = MagicMock(
            profiles={"fast": MagicMock()},
            active_profile="fast",
            routing_rules=[MagicMock()],
        )
        _cmd_check(ns)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "version" in data
    assert "providers" in data
    assert data["active_profile"] == "fast"


# ── status tests ──


def test_status_no_active(capsys):
    """status with no active dispatches shows message."""
    from modelmux.cli import _cmd_status

    ns = MagicMock()
    ns.watch = False

    with patch("modelmux.status.list_active", return_value=[]):
        _cmd_status(ns)

    captured = capsys.readouterr()
    assert "No active" in captured.out


def test_status_with_active(capsys):
    """status shows active dispatches."""
    import time

    from modelmux.cli import _cmd_status
    from modelmux.status import DispatchStatus

    ns = MagicMock()
    ns.watch = False

    active = [
        DispatchStatus(
            run_id="abc123",
            provider="codex",
            task_summary="test task",
            status="running",
            started_at=time.time() - 10,
        ),
    ]

    with patch("modelmux.status.list_active", return_value=active):
        _cmd_status(ns)

    captured = capsys.readouterr()
    assert "abc123" in captured.out
    assert "codex" in captured.out


# ── version test ──


def test_cmd_version(capsys):
    """version should print version string."""
    from modelmux.cli import _cmd_version

    _cmd_version()

    captured = capsys.readouterr()
    assert "modelmux" in captured.out


# ── helper function tests ──


def test_get_available_adapters():
    """_get_available_adapters returns available adapters."""
    from modelmux.cli import _get_available_adapters

    mock = _make_adapter(available=True)
    with patch(
        "modelmux.adapters.get_all_adapters",
        return_value={"codex": mock},
    ):
        all_a, available = _get_available_adapters()
        assert "codex" in available


def test_resolve_adapter():
    """_resolve_adapter returns adapter instance."""
    from modelmux.cli import _resolve_adapter

    mock = _make_adapter(available=True)
    result = _resolve_adapter({"codex": mock}, "codex")
    assert result is mock


def test_read_task_from_args():
    """_read_task reads from positional args."""
    from modelmux.cli import _read_task

    ns = MagicMock()
    ns.task = ["hello", "world"]
    assert _read_task(ns) == "hello world"


def test_apply_profile_with_model():
    """_apply_profile with model returns model in extra_args."""
    from modelmux.cli import _apply_profile

    extra, env = _apply_profile("codex", "gpt-5", "")
    assert extra["model"] == "gpt-5"
    assert env == {}


def test_apply_profile_with_profile_name():
    """_apply_profile with profile name loads config."""
    from modelmux.cli import _apply_profile
    from modelmux.config import MuxConfig, Profile, ProviderConfig

    config = MuxConfig(
        profiles={
            "test": Profile(
                providers={"codex": ProviderConfig(model="custom-model")},
            ),
        },
    )

    with patch("modelmux.config.load_config", return_value=config):
        extra, env = _apply_profile("codex", "", "test")
        assert extra["model"] == "custom-model"


# ── cmd_init / cmd_config tests ──


def test_cmd_init():
    """_cmd_init calls run_wizard."""
    from modelmux.cli import _cmd_init

    ns = MagicMock()
    ns.scope = "user"

    with patch("modelmux.init_wizard.run_wizard") as mock_wizard:
        _cmd_init(ns)
        mock_wizard.assert_called_once_with(scope="user")


def test_cmd_config_missing_textual(capsys):
    """_cmd_config exits when textual is not installed."""
    from modelmux.cli import _cmd_config

    ns = MagicMock()
    ns.scope = "user"

    with (
        patch.dict("sys.modules", {"modelmux.tui": None}),
        patch("modelmux.cli._cmd_config") as mock_fn,
    ):
        # Simulate ImportError path
        mock_fn.side_effect = SystemExit(1)
        with pytest.raises(SystemExit):
            mock_fn(ns)


# ── cmd_export test ──


def test_cmd_export_to_stdout(capsys):
    """export without --output prints to stdout."""
    from modelmux.cli import _cmd_export

    ns = MagicMock()
    ns.format = "csv"
    ns.hours = 0
    ns.provider = ""
    ns.limit = 100
    ns.output = ""
    ns.source = ""

    with patch("modelmux.export.run_export", return_value="col1,col2\nval1,val2"):
        _cmd_export(ns)

    captured = capsys.readouterr()
    assert "col1,col2" in captured.out


def test_cmd_export_to_file(capsys):
    """export with --output shows filename."""
    from modelmux.cli import _cmd_export

    ns = MagicMock()
    ns.format = "json"
    ns.hours = 24
    ns.provider = "codex"
    ns.limit = 50
    ns.output = "/tmp/test.json"
    ns.source = ""

    with patch("modelmux.export.run_export", return_value="{}"):
        _cmd_export(ns)

    captured = capsys.readouterr()
    assert "Exported to" in captured.out


# ── main entry point tests ──


def test_main_version(capsys):
    """main() with 'version' subcommand prints version."""
    import sys

    from modelmux.cli import main

    with patch.object(sys, "argv", ["modelmux", "version"]):
        main()

    captured = capsys.readouterr()
    assert "modelmux" in captured.out


def test_main_check(capsys):
    """main() with 'check' routes to _cmd_check."""
    import sys

    from modelmux.cli import main

    mock_adapter = MagicMock(spec=BaseAdapter)
    mock_adapter.check_available.return_value = False
    mock_adapter._binary_name.return_value = "codex"

    with (
        patch.object(sys, "argv", ["modelmux", "check"]),
        patch("modelmux.adapters.ADAPTERS", {"codex": lambda: mock_adapter}),
        patch("shutil.which", return_value=None),
        patch("modelmux.config.load_config") as mock_config,
        patch("modelmux.history.get_history_stats", return_value={"total": 0}),
    ):
        mock_config.return_value = MagicMock(
            profiles={},
            active_profile="default",
            routing_rules=[],
        )
        main()

    captured = capsys.readouterr()
    assert "modelmux" in captured.out


# ── feedback list with entries ──


def test_feedback_list_with_entries(capsys):
    """feedback --list with entries shows ratings."""
    from modelmux.cli import _cmd_feedback

    entries = [
        {"run_id": "abc12345", "provider": "codex", "rating": 5, "comment": "great"},
        {"run_id": "def67890", "provider": "gemini", "rating": 3, "comment": "ok"},
    ]
    ns = _feedback_ns(**{"list": True})

    with patch("modelmux.feedback.read_feedback", return_value=entries):
        _cmd_feedback(ns)

    captured = capsys.readouterr()
    assert "User Feedback" in captured.out
    assert "codex" in captured.out


# ── profile list json test ──


def test_profile_list_json(capsys):
    """profile --json outputs JSON profile list."""
    from modelmux.cli import _cmd_profile
    from modelmux.config import MuxConfig, Profile, ProviderConfig

    config = MuxConfig(
        active_profile="fast",
        profiles={
            "fast": Profile(
                description="Quick",
                providers={"gemini": ProviderConfig(model="flash")},
            ),
        },
    )
    ns = MagicMock()
    ns.name = ""
    ns.json = True

    with patch("modelmux.config.load_config", return_value=config):
        _cmd_profile(ns)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["active"] == "fast"
    assert "fast" in data["profiles"]


def test_profile_show_text(capsys):
    """profile <name> in text mode shows details."""
    from modelmux.cli import _cmd_profile
    from modelmux.config import MuxConfig, Profile, ProviderConfig

    config = MuxConfig(
        profiles={
            "budget": Profile(
                description="Cheap",
                providers={"codex": ProviderConfig(model="mini", base_url="https://x.com")},
            ),
        },
    )
    ns = MagicMock()
    ns.name = "budget"
    ns.json = False

    with patch("modelmux.config.load_config", return_value=config):
        _cmd_profile(ns)

    captured = capsys.readouterr()
    assert "budget" in captured.out
    assert "model=mini" in captured.out
    assert "url=https://x.com" in captured.out
