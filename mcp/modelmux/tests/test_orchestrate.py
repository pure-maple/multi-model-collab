"""Tests for mux_orchestrate domain logic."""

import pytest

from modelmux.orchestrate import (
    OrchestrateError,
    TaskState,
    apply_action,
    available_roles,
    create_task,
    infer_role,
    normalize_action,
    summarize_task,
)


class TestRoleCatalog:
    def test_available_roles_exposes_metadata(self):
        roles = available_roles()
        assert "implementer" in roles
        assert roles["reviewer"]["recommended_models"]
        assert "review" in roles["reviewer"]["skills"]

    def test_infer_role_matches_keywords(self):
        assert infer_role("write release notes for v1.2") == "writer"
        assert infer_role("debug flaky test in CI") == "debugger"
        assert infer_role("implement MER-14") == "implementer"


class TestTaskCreation:
    def test_summarize_task_collapses_whitespace(self):
        assert summarize_task("  fix   failing   tests  ") == "fix failing tests"

    def test_summarize_task_truncates_long_input(self):
        title = summarize_task("x" * 120, max_len=20)
        assert title.endswith("…")
        assert len(title) == 20

    def test_create_task_sets_defaults_and_event(self):
        task = create_task("plan the rollout", "T001")
        assert task.task_id == "T001"
        assert task.state is TaskState.PLANNED
        assert task.suggested_role == "planner"
        assert task.events[0]["action"] == "plan"

    def test_create_task_requires_task_id(self):
        with pytest.raises(OrchestrateError):
            create_task("test", "")

    def test_summarize_task_rejects_empty_input(self):
        with pytest.raises(OrchestrateError):
            summarize_task("   ")

    def test_normalize_action_rejects_unknown_values(self):
        with pytest.raises(OrchestrateError):
            normalize_action("ship")


class TestStateTransitions:
    def test_assign_review_merge_flow(self):
        task = create_task("implement feature", "T001")
        apply_action(task, "assign", role="implementer", agent="codex", branch="feat/x")
        assert task.state is TaskState.IMPLEMENTING
        assert task.agent == "codex"

        apply_action(task, "review")
        assert task.state is TaskState.REVIEWING

        apply_action(task, "merge")
        assert task.state is TaskState.INTEGRATED
        assert task.state.is_terminal() is True
        assert [event["action"] for event in task.events] == [
            "plan",
            "assign",
            "review",
            "merge",
        ]

    def test_assign_requires_known_role_and_agent(self):
        task = create_task("implement feature", "T001")
        with pytest.raises(OrchestrateError):
            apply_action(task, "assign", role="ghost", agent="codex")
        with pytest.raises(OrchestrateError):
            apply_action(task, "assign", role="", agent="codex")
        with pytest.raises(OrchestrateError):
            apply_action(task, "assign", role="implementer", agent="")

    def test_review_requires_assignment_and_branch(self):
        task = create_task("implement feature", "T001")
        with pytest.raises(OrchestrateError):
            apply_action(task, "review")

        apply_action(task, "assign", role="implementer", agent="codex")
        with pytest.raises(OrchestrateError):
            apply_action(task, "review")

    def test_merge_requires_reviewing_state(self):
        task = create_task("implement feature", "T001")
        apply_action(task, "assign", role="implementer", agent="codex", branch="feat/x")
        with pytest.raises(OrchestrateError):
            apply_action(task, "merge")

    def test_status_action_is_a_noop(self):
        task = create_task("implement feature", "T001")
        returned = apply_action(task, "status")
        assert returned is task

    def test_integrated_task_cannot_be_reassigned(self):
        task = create_task("implement feature", "T001")
        apply_action(task, "assign", role="implementer", agent="codex", branch="feat/x")
        apply_action(task, "review")
        apply_action(task, "merge")

        with pytest.raises(OrchestrateError):
            apply_action(task, "assign", role="implementer", agent="codex")

    def test_integrated_task_cannot_be_reviewed_again(self):
        task = create_task("implement feature", "T001")
        apply_action(task, "assign", role="implementer", agent="codex", branch="feat/x")
        apply_action(task, "review")
        apply_action(task, "merge")

        with pytest.raises(OrchestrateError):
            apply_action(task, "review")
        assert task.state is TaskState.INTEGRATED

    def test_merge_requires_branch_when_task_branch_is_cleared(self):
        task = create_task("implement feature", "T001")
        apply_action(task, "assign", role="implementer", agent="codex", branch="feat/x")
        apply_action(task, "review")
        task.branch = ""

        with pytest.raises(OrchestrateError):
            apply_action(task, "merge")

    def test_from_dict_defaults_invalid_state(self):
        task = create_task("implement feature", "T001")
        data = task.to_dict()
        data["state"] = "mystery"

        restored = task.from_dict(data)
        assert restored.state is TaskState.PLANNED
