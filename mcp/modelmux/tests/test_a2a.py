"""Tests for A2A collaboration engine."""

import asyncio

from vyane.a2a.types import (
    Artifact,
    AgentCard,
    CollaborationTask,
    ConvergenceDecision,
    ConvergenceSignal,
    Message,
    MessageRole,
    Part,
    Skill,
    TaskState,
    Turn,
)
from vyane.a2a.context import CollaborationContext
from vyane.a2a.convergence import evaluate, _check_structured_signals
from vyane.a2a.patterns import (
    BUILTIN_PATTERNS,
    get_pattern,
    list_patterns,
)
from vyane.a2a.engine import CollaborationEngine, EngineConfig
from vyane.adapters.base import AdapterResult, BaseAdapter


# --- Fake adapter for testing ---

class FakeCollabAdapter(BaseAdapter):
    """Adapter that returns canned responses for testing."""

    provider_name = "fake"
    _response: str = "CONVERGED: looks good"
    _call_count: int = 0

    def __init__(self, response: str = "CONVERGED: looks good"):
        self._response = response
        self._call_count = 0

    def _binary_name(self) -> str:
        return "echo"

    def check_available(self) -> bool:
        return True

    def build_command(self, prompt, workdir, sandbox="read-only",
                      session_id="", extra_args=None):
        return ["echo", "test"]

    def parse_output(self, lines):
        return self._response, "", ""

    async def run(self, prompt="", workdir=".", sandbox="read-only",
                  session_id="", timeout=300, extra_args=None,
                  env_overrides=None, on_progress=None):
        self._call_count += 1
        return AdapterResult(
            run_id=f"fake-{self._call_count}",
            provider=self.provider_name,
            status="success",
            summary=self._response[:200],
            output=self._response,
        )


# --- Type tests ---

def test_task_state_terminal():
    assert TaskState.COMPLETED.is_terminal()
    assert TaskState.FAILED.is_terminal()
    assert not TaskState.WORKING.is_terminal()
    assert not TaskState.INPUT_REQUIRED.is_terminal()


def test_task_state_interrupted():
    assert TaskState.INPUT_REQUIRED.is_interrupted()
    assert TaskState.AUTH_REQUIRED.is_interrupted()
    assert not TaskState.WORKING.is_interrupted()


def test_task_transition():
    task = CollaborationTask(goal="test")
    assert task.state == TaskState.SUBMITTED
    task.transition(TaskState.WORKING)
    assert task.state == TaskState.WORKING
    task.transition(TaskState.COMPLETED)
    assert task.state == TaskState.COMPLETED
    assert task.completed_at > 0


def test_task_transition_from_terminal_fails():
    task = CollaborationTask(goal="test")
    task.transition(TaskState.COMPLETED)
    try:
        task.transition(TaskState.WORKING)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_message_text_factory():
    msg = Message.text(MessageRole.AGENT, "hello world", provider="codex")
    assert msg.role == MessageRole.AGENT
    assert msg.parts[0].text == "hello world"
    assert msg.metadata["provider"] == "codex"


def test_artifact_auto_id():
    art = Artifact(name="test")
    assert art.artifact_id.startswith("art-")


def test_turn_auto_id():
    turn = Turn(provider="codex", role="implementer")
    assert turn.turn_id.startswith("turn-")


def test_agent_card_to_dict():
    card = AgentCard(
        name="Vyane",
        version="0.18.0",
        skills=[Skill(id="review", name="Review", description="Code review")],
    )
    d = card.to_dict()
    assert d["name"] == "Vyane"
    assert len(d["skills"]) == 1
    assert d["skills"][0]["id"] == "review"


# --- Pattern tests ---

def test_builtin_patterns_exist():
    assert "review" in BUILTIN_PATTERNS
    assert "consensus" in BUILTIN_PATTERNS
    assert "debate" in BUILTIN_PATTERNS


def test_get_pattern():
    p = get_pattern("review")
    assert p is not None
    assert "implementer" in p.roles
    assert "reviewer" in p.roles


def test_list_patterns():
    listing = list_patterns()
    assert len(listing) == 3
    assert "review" in listing
    assert "roles" in listing["review"]


# --- Context tests ---

def test_context_from_task():
    task = CollaborationTask(goal="write tests", constraints=["no mocking"])
    ctx = CollaborationContext.from_task(task)
    assert ctx.goal == "write tests"
    assert "no mocking" in ctx.constraints


def test_context_build_prompt():
    task = CollaborationTask(goal="implement API")
    ctx = CollaborationContext.from_task(task)
    prompt = ctx.build_prompt(
        agent_role="implementer",
        role_description="You write code.",
        current_instruction="Build a REST API",
        task=task,
    )
    assert "implementer" in prompt
    assert "implement API" in prompt
    assert "Build a REST API" in prompt
    assert "CONVERGED" in prompt


def test_context_artifact_index():
    task = CollaborationTask(goal="test")
    ctx = CollaborationContext.from_task(task)
    art = Artifact(name="main.py", parts=[Part(text="def hello(): pass")])
    ctx._index_artifact(art, turn_id="t1")
    assert len(ctx.artifact_refs) == 1
    assert ctx.artifact_refs[0].name == "main.py"


# --- Convergence tests ---

def test_convergence_max_rounds():
    task = CollaborationTask(goal="test", max_rounds=3)
    task.turns = [Turn(), Turn(), Turn()]
    turn = Turn(output="some output")
    signal = evaluate(task, turn)
    assert signal.decision == ConvergenceDecision.COMPLETE
    assert "max rounds" in signal.reason.lower()


def test_convergence_explicit_signal():
    turn = Turn(output="CONVERGED: all tests pass", role="reviewer")
    signal = _check_structured_signals(turn)
    assert signal is not None
    assert signal.decision == ConvergenceDecision.COMPLETE


def test_convergence_lgtm():
    turn = Turn(output="Everything LGTM, ship it!", role="reviewer")
    signal = _check_structured_signals(turn)
    assert signal is not None
    assert signal.decision == ConvergenceDecision.COMPLETE


def test_convergence_needs_input():
    turn = Turn(output="NEEDS_INPUT: unclear requirements", role="reviewer")
    signal = _check_structured_signals(turn)
    assert signal is not None
    assert signal.decision == ConvergenceDecision.NEEDS_INPUT


def test_convergence_blocking_issues():
    turn = Turn(
        output="Found blocking issue: SQL injection vulnerability",
        role="reviewer",
    )
    signal = _check_structured_signals(turn)
    assert signal is not None
    assert signal.decision == ConvergenceDecision.CONTINUE


def test_convergence_no_signal():
    turn = Turn(output="Here is some regular output", role="implementer")
    signal = _check_structured_signals(turn)
    assert signal is None


# --- Engine tests ---

def test_engine_unknown_pattern():
    adapter = FakeCollabAdapter()
    engine = CollaborationEngine(
        get_adapter=lambda p: adapter,
        config=EngineConfig(),
    )
    result = asyncio.run(engine.run(
        task="test", pattern_name="nonexistent",
    ))
    assert result.state == TaskState.FAILED
    assert "Unknown pattern" in result.metadata.get("error", "")


def test_engine_review_converges():
    """Review pattern should converge when adapter returns CONVERGED."""
    adapter = FakeCollabAdapter(response="CONVERGED: everything looks great")
    engine = CollaborationEngine(
        get_adapter=lambda p: adapter,
        config=EngineConfig(),
    )
    result = asyncio.run(engine.run(
        task="write a hello world function",
        pattern_name="review",
    ))
    assert result.state == TaskState.COMPLETED
    assert len(result.turns) >= 1


def test_engine_debate_runs():
    """Debate pattern should complete."""
    adapter = FakeCollabAdapter(response="The proposal has merit. CONVERGED: verdict issued.")
    engine = CollaborationEngine(
        get_adapter=lambda p: adapter,
        config=EngineConfig(),
    )
    result = asyncio.run(engine.run(
        task="Should we use microservices?",
        pattern_name="debate",
    ))
    assert result.state == TaskState.COMPLETED


def test_engine_cancel_event():
    """Engine should respect cancel_event and transition to CANCELED."""
    cancel = asyncio.Event()
    cancel.set()  # Set immediately — engine should stop before any dispatch

    adapter = FakeCollabAdapter(response="This should not run")
    engine = CollaborationEngine(
        get_adapter=lambda p: adapter,
        config=EngineConfig(cancel_event=cancel),
    )
    result = asyncio.run(engine.run(
        task="this should be canceled",
        pattern_name="review",
    ))
    assert result.state == TaskState.CANCELED
    # Should have zero or very few turns since we canceled immediately
    assert len(result.turns) == 0


# --- Provider/Model spec tests ---

def test_engine_parse_provider_spec():
    """_parse_provider_spec correctly splits provider/model."""
    assert CollaborationEngine._parse_provider_spec("codex") == ("codex", "")
    assert CollaborationEngine._parse_provider_spec("dashscope/kimi-k2.5") == (
        "dashscope",
        "kimi-k2.5",
    )
    assert CollaborationEngine._parse_provider_spec("dashscope/MiniMax-M2.5") == (
        "dashscope",
        "MiniMax-M2.5",
    )


def test_engine_provider_model_in_overrides():
    """Provider overrides with provider/model syntax should work."""
    captured_extra_args = []

    class TrackingAdapter(FakeCollabAdapter):
        async def run(self, prompt="", workdir=".", sandbox="read-only",
                      session_id="", timeout=300, extra_args=None,
                      env_overrides=None, on_progress=None):
            captured_extra_args.append(extra_args)
            return await super().run(
                prompt, workdir, sandbox, session_id, timeout,
                extra_args, env_overrides, on_progress,
            )

    adapter = TrackingAdapter(response="CONVERGED: looks good")
    engine = CollaborationEngine(
        get_adapter=lambda p: adapter,
        config=EngineConfig(),
    )
    result = asyncio.run(engine.run(
        task="test dashscope model",
        pattern_name="review",
        providers={
            "implementer": "dashscope/kimi-k2.5",
            "reviewer": "dashscope/MiniMax-M2.5",
            "reviser": "dashscope/kimi-k2.5",
        },
    ))
    assert result.state == TaskState.COMPLETED
    # At least one call should have model in extra_args
    models_seen = [ea.get("model") for ea in captured_extra_args if ea]
    assert "kimi-k2.5" in models_seen or "MiniMax-M2.5" in models_seen


def test_engine_resolve_providers_preserves_spec():
    """_resolve_providers should preserve provider/model specs from overrides."""
    adapter = FakeCollabAdapter()
    engine = CollaborationEngine(
        get_adapter=lambda p: adapter,
        config=EngineConfig(),
    )
    pattern = get_pattern("review")
    mapping = engine._resolve_providers(
        pattern,
        {"implementer": "dashscope/kimi-k2.5", "reviewer": "claude"},
    )
    assert mapping["implementer"] == "dashscope/kimi-k2.5"
    assert mapping["reviewer"] == "claude"
    # reviser falls back to pattern default
    assert mapping["reviser"] == "codex"


def test_engine_plain_provider_no_extra_args():
    """Plain provider without /model should not pass model in extra_args."""
    captured_extra_args = []

    class TrackingAdapter(FakeCollabAdapter):
        async def run(self, prompt="", workdir=".", sandbox="read-only",
                      session_id="", timeout=300, extra_args=None,
                      env_overrides=None, on_progress=None):
            captured_extra_args.append(extra_args)
            return await super().run(
                prompt, workdir, sandbox, session_id, timeout,
                extra_args, env_overrides, on_progress,
            )

    adapter = TrackingAdapter(response="CONVERGED: approved")
    engine = CollaborationEngine(
        get_adapter=lambda p: adapter,
        config=EngineConfig(),
    )
    asyncio.run(engine.run(
        task="test plain provider",
        pattern_name="review",
        providers={"implementer": "codex", "reviewer": "gemini", "reviser": "codex"},
    ))
    # All calls should have None extra_args (no model specified)
    assert all(ea is None for ea in captured_extra_args)
