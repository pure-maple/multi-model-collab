"""Tests for the A2A context accumulation module."""

from vyane.a2a.context import (
    DEFAULT_CONTEXT_BUDGET,
    ArtifactRef,
    CollaborationContext,
)
from vyane.a2a.types import Artifact, CollaborationTask, Part, Turn


def _make_task(**kwargs):
    defaults = {"goal": "Build a REST API", "max_rounds": 5, "max_wall_time": 600}
    defaults.update(kwargs)
    return CollaborationTask(**defaults)


def _make_turn(**kwargs):
    defaults = {
        "turn_id": "1",
        "role": "implementer",
        "provider": "codex",
        "output": "Done",
        "status": "success",
    }
    defaults.update(kwargs)
    return Turn(**defaults)


class TestArtifactRef:
    def test_defaults(self):
        ref = ArtifactRef()
        assert ref.artifact_id == ""
        assert ref.name == ""
        assert ref.summary == ""
        assert ref.content_hash == ""
        assert ref.size_chars == 0
        assert ref.turn_id == ""


class TestCollaborationContext:
    def test_defaults(self):
        ctx = CollaborationContext()
        assert ctx.goal == ""
        assert ctx.constraints == []
        assert ctx.acceptance_criteria == ""
        assert ctx.rolling_summary == ""
        assert ctx.artifact_refs == []
        assert ctx.recent_window_size == 2
        assert ctx.context_budget_tokens == DEFAULT_CONTEXT_BUDGET


class TestFromTask:
    def test_basic(self):
        task = _make_task(goal="Build API", constraints=["Use FastAPI"])
        ctx = CollaborationContext.from_task(task)
        assert ctx.goal == "Build API"
        assert ctx.constraints == ["Use FastAPI"]

    def test_indexes_existing_artifacts(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="code",
                    name="main.py",
                    parts=[Part(text="print('hi')")],
                )
            ]
        )
        ctx = CollaborationContext.from_task(task)
        assert len(ctx.artifact_refs) == 1
        assert ctx.artifact_refs[0].artifact_id == "code"
        assert ctx.artifact_refs[0].name == "main.py"


class TestBuildPrompt:
    def test_basic_prompt(self):
        task = _make_task(goal="Fix bug")
        ctx = CollaborationContext.from_task(task)
        prompt = ctx.build_prompt(
            agent_role="implementer",
            role_description="You fix bugs",
            current_instruction="Fix the null check",
            task=task,
        )
        assert "implementer" in prompt
        assert "Fix bug" in prompt
        assert "Fix the null check" in prompt
        assert "CONVERGED" in prompt

    def test_with_acceptance_criteria(self):
        task = _make_task(goal="test")
        ctx = CollaborationContext.from_task(task)
        ctx.acceptance_criteria = "All tests pass"
        prompt = ctx.build_prompt("a", "d", "i", task)
        assert "Acceptance Criteria" in prompt
        assert "All tests pass" in prompt

    def test_with_constraints(self):
        task = _make_task(goal="test", constraints=["Use Python", "No deps"])
        ctx = CollaborationContext.from_task(task)
        prompt = ctx.build_prompt("a", "d", "i", task)
        assert "Constraints" in prompt
        assert "Use Python" in prompt
        assert "No deps" in prompt

    def test_with_rolling_summary(self):
        task = _make_task(goal="test")
        ctx = CollaborationContext.from_task(task)
        ctx.rolling_summary = "Round 1: initial implementation"
        prompt = ctx.build_prompt("a", "d", "i", task)
        assert "Collaboration Progress" in prompt
        assert "initial implementation" in prompt

    def test_with_recent_turns(self):
        turns = [
            _make_turn(turn_id="1", role="impl", provider="codex", output="Code v1"),
            _make_turn(turn_id="2", role="rev", provider="gemini", output="LGTM"),
        ]
        task = _make_task(goal="test", turns=turns)
        ctx = CollaborationContext.from_task(task)
        prompt = ctx.build_prompt("a", "d", "i", task)
        assert "Recent Agent Outputs" in prompt
        assert "Code v1" in prompt
        assert "LGTM" in prompt

    def test_long_output_truncated(self):
        long_output = "x" * 5000
        turns = [
            _make_turn(turn_id="1", output=long_output),
        ]
        task = _make_task(goal="test", turns=turns)
        ctx = CollaborationContext.from_task(task)
        prompt = ctx.build_prompt("a", "d", "i", task)
        assert "[truncated]" in prompt

    def test_long_output_uses_summary(self):
        turns = [
            _make_turn(
                turn_id="1",
                output="x" * 5000,
                output_summary="Brief summary of work",
            ),
        ]
        task = _make_task(goal="test", turns=turns)
        ctx = CollaborationContext.from_task(task)
        prompt = ctx.build_prompt("a", "d", "i", task)
        assert "Brief summary of work" in prompt

    def test_with_artifact_refs(self):
        task = _make_task(goal="test")
        ctx = CollaborationContext.from_task(task)
        ctx.artifact_refs.append(
            ArtifactRef(
                artifact_id="a1",
                name="result.py",
                summary="Main module",
                content_hash="abc12345678",
                size_chars=500,
            )
        )
        prompt = ctx.build_prompt("a", "d", "i", task)
        assert "Shared Artifacts" in prompt
        assert "result.py" in prompt
        assert "abc12345" in prompt

    def test_with_output_schema(self):
        task = _make_task(goal="test")
        ctx = CollaborationContext.from_task(task)
        prompt = ctx.build_prompt("a", "d", "i", task, output_schema="Return JSON")
        assert "Required Output Format" in prompt
        assert "Return JSON" in prompt


class TestUpdateAfterTurn:
    def test_indexes_new_artifacts(self):
        task = _make_task(goal="test")
        ctx = CollaborationContext.from_task(task)
        turn = _make_turn(
            artifacts=[
                Artifact(
                    artifact_id="new",
                    name="new.py",
                    parts=[Part(text="new code")],
                )
            ]
        )
        task.turns.append(turn)
        ctx.update_after_turn(turn, task)
        assert len(ctx.artifact_refs) == 1
        assert ctx.artifact_refs[0].artifact_id == "new"

    def test_updates_existing_artifact(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="code",
                    parts=[Part(text="v1")],
                )
            ]
        )
        ctx = CollaborationContext.from_task(task)
        original_hash = ctx.artifact_refs[0].content_hash

        turn = _make_turn(
            artifacts=[
                Artifact(
                    artifact_id="code",
                    parts=[Part(text="v2 updated")],
                )
            ]
        )
        task.turns.append(turn)
        ctx.update_after_turn(turn, task)

        assert len(ctx.artifact_refs) == 1
        assert ctx.artifact_refs[0].content_hash != original_hash

    def test_rolling_summary_updated(self):
        turns = [
            _make_turn(turn_id=str(i), output=f"Work {i}") for i in range(5)
        ]
        task = _make_task(goal="test", turns=turns[:-1])
        ctx = CollaborationContext.from_task(task)
        ctx.update_after_turn(turns[-1], task)
        # After enough turns, rolling summary should be populated
        # (depends on recent_window_size=2, so older turns get compressed)


class TestCompressTurns:
    def test_compresses(self):
        ctx = CollaborationContext()
        turns = [
            _make_turn(turn_id="1", role="impl", provider="codex", output="Built API"),
            _make_turn(turn_id="2", role="rev", provider="gemini", output="LGTM"),
        ]
        summary = ctx._compress_turns(turns)
        assert "impl/codex" in summary
        assert "rev/gemini" in summary
        assert "✓" in summary  # success markers

    def test_error_marker(self):
        ctx = CollaborationContext()
        turns = [_make_turn(turn_id="1", status="error", output="Failed")]
        summary = ctx._compress_turns(turns)
        assert "✗" in summary

    def test_uses_output_summary(self):
        ctx = CollaborationContext()
        turns = [
            _make_turn(
                turn_id="1",
                output="x" * 500,
                output_summary="Brief version",
            )
        ]
        summary = ctx._compress_turns(turns)
        assert "Brief version" in summary


class TestIndexArtifact:
    def test_adds_new(self):
        ctx = CollaborationContext()
        art = Artifact(
            artifact_id="a1",
            name="test.py",
            parts=[Part(text="content")],
        )
        ctx._index_artifact(art, turn_id="t1")
        assert len(ctx.artifact_refs) == 1
        assert ctx.artifact_refs[0].name == "test.py"
        assert ctx.artifact_refs[0].turn_id == "t1"

    def test_updates_existing(self):
        ctx = CollaborationContext()
        art1 = Artifact(
            artifact_id="a1",
            parts=[Part(text="v1")],
        )
        ctx._index_artifact(art1, turn_id="t1")
        hash1 = ctx.artifact_refs[0].content_hash

        art2 = Artifact(
            artifact_id="a1",
            parts=[Part(text="v2")],
        )
        ctx._index_artifact(art2, turn_id="t2")

        assert len(ctx.artifact_refs) == 1
        assert ctx.artifact_refs[0].content_hash != hash1
        assert ctx.artifact_refs[0].turn_id == "t2"

    def test_uses_artifact_id_as_name_fallback(self):
        ctx = CollaborationContext()
        art = Artifact(artifact_id="myid", name="", parts=[Part(text="x")])
        ctx._index_artifact(art, turn_id="t1")
        assert ctx.artifact_refs[0].name == "myid"


class TestEstimateTokens:
    def test_basic(self):
        task = _make_task(goal="Short goal")
        ctx = CollaborationContext.from_task(task)
        tokens = ctx.estimate_tokens(task)
        assert tokens > 0

    def test_with_turns_and_artifacts(self):
        turns = [_make_turn(output="x" * 400)]
        task = _make_task(goal="g", turns=turns)
        ctx = CollaborationContext.from_task(task)
        ctx.rolling_summary = "summary " * 10
        tokens = ctx.estimate_tokens(task)
        assert tokens > 100
