"""Tests for the convergence detection module."""

from vyane.a2a.convergence import (
    _check_hard_limits,
    _check_stability,
    _check_structured_signals,
    _compute_artifact_hashes,
    build_judge_prompt,
    evaluate,
)
from vyane.a2a.types import (
    Artifact,
    CollaborationTask,
    ConvergenceDecision,
    Part,
    Turn,
)


def _make_task(**kwargs):
    defaults = {"goal": "test", "max_rounds": 5, "max_wall_time": 600}
    defaults.update(kwargs)
    task = CollaborationTask(**defaults)
    return task


def _make_turn(**kwargs):
    defaults = {
        "turn_id": "1",
        "role": "implementer",
        "provider": "codex",
        "output": "",
    }
    defaults.update(kwargs)
    return Turn(**defaults)


class TestCheckHardLimits:
    def test_max_rounds(self):
        turns = [_make_turn(turn_id=str(i)) for i in range(5)]
        task = _make_task(max_rounds=5, turns=turns)
        sig = _check_hard_limits(task)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.COMPLETE
        assert "max rounds" in sig.reason

    def test_max_wall_time(self):
        import time

        task = _make_task(
            max_wall_time=600,
            created_at=time.time() - 601,
        )
        sig = _check_hard_limits(task)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.COMPLETE
        assert "wall time" in sig.reason

    def test_below_limits(self):
        turns = [_make_turn(turn_id=str(i)) for i in range(2)]
        task = _make_task(turns=turns)
        sig = _check_hard_limits(task)
        assert sig is None

    def test_consecutive_failures(self):
        turns = [
            _make_turn(turn_id=str(i), status="error") for i in range(3)
        ]
        task = _make_task(turns=turns)
        sig = _check_hard_limits(task)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.FAILED
        assert "consecutive" in sig.reason

    def test_two_failures_not_enough(self):
        turns = [
            _make_turn(turn_id="1", status="error"),
            _make_turn(turn_id="2", status="error"),
        ]
        task = _make_task(turns=turns)
        sig = _check_hard_limits(task)
        assert sig is None

    def test_success_breaks_failure_streak(self):
        turns = [
            _make_turn(turn_id="1", status="error"),
            _make_turn(turn_id="2", status="success"),
            _make_turn(turn_id="3", status="error"),
            _make_turn(turn_id="4", status="error"),
        ]
        task = _make_task(turns=turns)
        sig = _check_hard_limits(task)
        assert sig is None


class TestCheckStructuredSignals:
    def test_converged_explicit(self):
        turn = _make_turn(output="CONVERGED: all tests pass")
        sig = _check_structured_signals(turn)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.COMPLETE
        assert "all tests pass" in sig.reason

    def test_lgtm(self):
        turn = _make_turn(output="The code looks good. LGTM!")
        sig = _check_structured_signals(turn)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.COMPLETE

    def test_approved(self):
        turn = _make_turn(output="APPROVED by reviewer")
        sig = _check_structured_signals(turn)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.COMPLETE

    def test_no_issues_found(self):
        turn = _make_turn(output="no remaining issues found")
        sig = _check_structured_signals(turn)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.COMPLETE

    def test_needs_input(self):
        turn = _make_turn(output="NEEDS_INPUT: clarify requirements")
        sig = _check_structured_signals(turn)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.NEEDS_INPUT

    def test_blocking_issue_from_reviewer(self):
        turn = _make_turn(
            output="blocking issue: SQL injection vulnerability",
            role="reviewer",
        )
        sig = _check_structured_signals(turn)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.CONTINUE
        assert len(sig.blocking_issues) > 0

    def test_blocking_issue_from_non_reviewer_ignored(self):
        turn = _make_turn(
            output="blocking issue found",
            role="implementer",
        )
        sig = _check_structured_signals(turn)
        # Non-reviewer blocking issues are not decisive
        assert sig is None

    def test_must_fix(self):
        turn = _make_turn(
            output="must fix this race condition before merge",
            role="critic",
        )
        sig = _check_structured_signals(turn)
        assert sig is not None
        assert sig.decision == ConvergenceDecision.CONTINUE

    def test_no_signals(self):
        turn = _make_turn(output="Just some normal output text.")
        sig = _check_structured_signals(turn)
        assert sig is None

    def test_empty_output(self):
        turn = _make_turn(output="")
        sig = _check_structured_signals(turn)
        assert sig is None


class TestCheckStability:
    def test_identical_hashes(self):
        h = {"art1": "abc123", "art2": "def456"}
        sig = _check_stability(h, dict(h))
        assert sig is not None
        assert sig.decision == ConvergenceDecision.COMPLETE
        assert "stabilized" in sig.reason

    def test_changed_hashes(self):
        current = {"art1": "new_hash"}
        previous = {"art1": "old_hash"}
        sig = _check_stability(current, previous)
        assert sig is None

    def test_different_artifact_sets(self):
        current = {"art1": "h1", "art2": "h2"}
        previous = {"art1": "h1"}
        sig = _check_stability(current, previous)
        assert sig is None

    def test_empty_current(self):
        sig = _check_stability({}, {"a": "h"})
        assert sig is None

    def test_empty_previous(self):
        sig = _check_stability({"a": "h"}, {})
        assert sig is None

    def test_both_empty(self):
        sig = _check_stability({}, {})
        assert sig is None


class TestComputeArtifactHashes:
    def test_single_artifact(self):
        task = _make_task(artifacts=[
            Artifact(
                artifact_id="a1",
                parts=[Part(text="hello world")],
            )
        ])
        hashes = _compute_artifact_hashes(task)
        assert "a1" in hashes
        assert len(hashes["a1"]) == 64  # SHA-256 hex digest

    def test_no_artifacts(self):
        task = _make_task(artifacts=[])
        hashes = _compute_artifact_hashes(task)
        assert hashes == {}

    def test_same_content_same_hash(self):
        task = _make_task(artifacts=[
            Artifact(artifact_id="a1", parts=[Part(text="same")]),
            Artifact(artifact_id="a2", parts=[Part(text="same")]),
        ])
        hashes = _compute_artifact_hashes(task)
        assert hashes["a1"] == hashes["a2"]


class TestEvaluate:
    def test_default_continue(self):
        task = _make_task(turns=[_make_turn(turn_id="0")])
        turn = _make_turn(output="Working on it...")
        sig = evaluate(task, turn)
        assert sig.decision == ConvergenceDecision.CONTINUE

    def test_max_rounds_takes_priority(self):
        turns = [_make_turn(turn_id=str(i)) for i in range(5)]
        task = _make_task(max_rounds=5, turns=turns)
        turn = _make_turn(output="LGTM")
        sig = evaluate(task, turn)
        # Hard limit checked first
        assert sig.decision == ConvergenceDecision.COMPLETE
        assert "max rounds" in sig.reason

    def test_stability_detection(self):
        task = _make_task(artifacts=[
            Artifact(artifact_id="code", parts=[Part(text="def foo(): pass")])
        ])
        turn = _make_turn(output="Looks fine")
        prev_hashes = _compute_artifact_hashes(task)
        sig = evaluate(task, turn, previous_artifact_hashes=prev_hashes)
        assert sig.decision == ConvergenceDecision.COMPLETE
        assert "stabilized" in sig.reason

    def test_returns_artifact_hashes_in_metadata(self):
        turns = [_make_turn(turn_id="0")]
        task = _make_task(turns=turns)
        turn = _make_turn(output="progress")
        sig = evaluate(task, turn)
        assert "artifact_hashes" in sig.metadata


class TestBuildJudgePrompt:
    def test_basic_prompt(self):
        task = _make_task(
            goal="Fix the bug",
            turns=[
                _make_turn(
                    turn_id="1",
                    role="implementer",
                    provider="codex",
                    output="Fixed the null check",
                ),
                _make_turn(
                    turn_id="2",
                    role="reviewer",
                    provider="gemini",
                    output="Looks good, no issues",
                ),
            ],
        )
        prompt = build_judge_prompt(task)
        assert "Fix the bug" in prompt
        assert "convergence judge" in prompt
        assert "CONTINUE" in prompt
        assert "COMPLETE" in prompt

    def test_includes_recent_turns(self):
        task = _make_task(
            goal="Do task",
            turns=[
                _make_turn(turn_id="1", role="a", provider="p", output="Step 1"),
                _make_turn(turn_id="2", role="b", provider="q", output="Step 2"),
                _make_turn(turn_id="3", role="c", provider="r", output="Step 3"),
            ],
        )
        prompt = build_judge_prompt(task)
        # Only last 2 turns
        assert "Step 2" in prompt
        assert "Step 3" in prompt

    def test_no_reviewer_shows_na(self):
        task = _make_task(
            goal="test",
            turns=[
                _make_turn(turn_id="1", role="implementer", output="code"),
            ],
        )
        prompt = build_judge_prompt(task)
        assert "N/A" in prompt

    def test_uses_output_summary_when_available(self):
        task = _make_task(
            goal="test",
            turns=[
                _make_turn(
                    turn_id="1",
                    role="a",
                    provider="p",
                    output="x" * 500,
                    output_summary="Short summary",
                ),
            ],
        )
        prompt = build_judge_prompt(task)
        assert "Short summary" in prompt

    def test_single_turn(self):
        task = _make_task(
            goal="test",
            turns=[_make_turn(turn_id="1", output="Only one")],
        )
        prompt = build_judge_prompt(task)
        assert "Only one" in prompt
