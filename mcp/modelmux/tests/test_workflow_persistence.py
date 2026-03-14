"""Tests for workflow persistence (step-file recoverable workflows)."""

import json
import time

import pytest

from modelmux.workflow import (
    PersistentStep,
    StepState,
    Workflow,
    WorkflowState,
    WorkflowStep,
    create_workflow_state,
    find_resume_step,
    list_workflow_states,
    load_workflow_state,
    save_workflow_state,
)


@pytest.fixture
def state_dir(tmp_path):
    """Provide a temporary directory for workflow state files."""
    return tmp_path / "workflows"


@pytest.fixture
def sample_workflow():
    """A simple 3-step workflow for testing."""
    return Workflow(
        name="test-pipeline",
        description="Test pipeline",
        steps=[
            WorkflowStep(name="step_a", provider="codex", task="{input}"),
            WorkflowStep(name="step_b", provider="claude", task="Review: {step_a}"),
            WorkflowStep(name="step_c", provider="gemini", task="Summarize: {step_b}"),
        ],
    )


class TestStepStateTransitions:
    """Test step state transitions."""

    def test_pending_to_running_to_completed(self):
        step = PersistentStep(name="s1")
        assert step.state == StepState.PENDING

        step.state = StepState.RUNNING
        step.started_at = time.time()
        assert step.state == StepState.RUNNING

        step.state = StepState.COMPLETED
        step.completed_at = time.time()
        step.result = {"output": "done", "status": "success"}
        assert step.state == StepState.COMPLETED
        assert step.result is not None

    def test_pending_to_running_to_failed(self):
        step = PersistentStep(name="s1")
        assert step.state == StepState.PENDING

        step.state = StepState.RUNNING
        step.started_at = time.time()
        assert step.state == StepState.RUNNING

        step.state = StepState.FAILED
        step.error = "timeout"
        step.completed_at = time.time()
        assert step.state == StepState.FAILED
        assert step.error == "timeout"

    def test_skipped_state(self):
        step = PersistentStep(name="s1")
        step.state = StepState.SKIPPED
        assert step.state == StepState.SKIPPED

    def test_retry_count_increments(self):
        step = PersistentStep(name="s1")
        assert step.retry_count == 0
        step.retry_count += 1
        assert step.retry_count == 1

    def test_step_state_values(self):
        assert StepState.PENDING == "pending"
        assert StepState.RUNNING == "running"
        assert StepState.COMPLETED == "completed"
        assert StepState.FAILED == "failed"
        assert StepState.SKIPPED == "skipped"


class TestWorkflowStatePersistence:
    """Test workflow state persistence to disk (write + read roundtrip)."""

    def test_save_and_load_roundtrip(self, state_dir, sample_workflow):
        state = create_workflow_state(
            "wf-001",
            sample_workflow,
            original_task="review this change",
        )
        state.status = "running"
        state.steps[0].state = StepState.COMPLETED
        state.steps[0].result = {"output": "result_a", "status": "success"}
        state.steps[0].completed_at = time.time()

        save_workflow_state(state, state_dir=state_dir)
        loaded = load_workflow_state("wf-001", state_dir=state_dir)

        assert loaded is not None
        assert loaded.workflow_id == "wf-001"
        assert loaded.workflow_name == "test-pipeline"
        assert loaded.original_task == "review this change"
        assert loaded.status == "running"
        assert len(loaded.steps) == 3
        assert loaded.steps[0].state == StepState.COMPLETED
        assert loaded.steps[0].result == {"output": "result_a", "status": "success"}
        assert loaded.steps[1].state == StepState.PENDING
        assert loaded.steps[2].state == StepState.PENDING

    def test_save_creates_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        state = WorkflowState(
            workflow_id="wf-nested",
            workflow_name="test",
            steps=[PersistentStep(name="s1")],
        )
        path = save_workflow_state(state, state_dir=nested)
        assert path.exists()
        assert nested.exists()

    def test_save_rejects_path_traversal_workflow_id(self, state_dir):
        state = WorkflowState(
            workflow_id="../wf-escape",
            workflow_name="test",
            steps=[PersistentStep(name="s1")],
        )
        with pytest.raises(ValueError):
            save_workflow_state(state, state_dir=state_dir)

    def test_save_overwrites_existing(self, state_dir, sample_workflow):
        state = create_workflow_state("wf-overwrite", sample_workflow)
        save_workflow_state(state, state_dir=state_dir)

        state.status = "completed"
        state.steps[0].state = StepState.COMPLETED
        save_workflow_state(state, state_dir=state_dir)

        loaded = load_workflow_state("wf-overwrite", state_dir=state_dir)
        assert loaded is not None
        assert loaded.status == "completed"
        assert loaded.steps[0].state == StepState.COMPLETED

    def test_load_nonexistent_returns_none(self, state_dir):
        result = load_workflow_state("does-not-exist", state_dir=state_dir)
        assert result is None

    def test_load_rejects_path_traversal_workflow_id(self, state_dir):
        result = load_workflow_state("../escape", state_dir=state_dir)
        assert result is None

    def test_load_corrupt_file_returns_none(self, state_dir):
        state_dir.mkdir(parents=True, exist_ok=True)
        bad_file = state_dir / "corrupt.json"
        bad_file.write_text("not valid json {{{")
        result = load_workflow_state("corrupt", state_dir=state_dir)
        assert result is None

    def test_state_file_is_valid_json(self, state_dir, sample_workflow):
        state = create_workflow_state("wf-json", sample_workflow)
        path = save_workflow_state(state, state_dir=state_dir)
        data = json.loads(path.read_text())
        assert data["workflow_id"] == "wf-json"
        assert isinstance(data["steps"], list)
        assert len(data["steps"]) == 3

    def test_updated_at_is_set_on_save(self, state_dir, sample_workflow):
        state = create_workflow_state("wf-ts", sample_workflow)
        state.updated_at = 0.0
        save_workflow_state(state, state_dir=state_dir)
        loaded = load_workflow_state("wf-ts", state_dir=state_dir)
        assert loaded is not None
        assert loaded.updated_at > 0.0


class TestResumeFromFailedStep:
    """Test resume from failed step (completed steps skipped)."""

    def test_find_resume_step_first_pending(self, sample_workflow):
        state = create_workflow_state("wf-r1", sample_workflow)
        assert find_resume_step(state) == 0

    def test_find_resume_step_after_first_completed(self, sample_workflow):
        state = create_workflow_state("wf-r2", sample_workflow)
        state.steps[0].state = StepState.COMPLETED
        assert find_resume_step(state) == 1

    def test_find_resume_step_after_failed(self, sample_workflow):
        state = create_workflow_state("wf-r3", sample_workflow)
        state.steps[0].state = StepState.COMPLETED
        state.steps[1].state = StepState.FAILED
        # Should resume from the failed step
        assert find_resume_step(state) == 1

    def test_find_resume_step_all_completed(self, sample_workflow):
        state = create_workflow_state("wf-r4", sample_workflow)
        for s in state.steps:
            s.state = StepState.COMPLETED
        assert find_resume_step(state) == -1

    def test_find_resume_step_skipped_steps_ignored(self, sample_workflow):
        state = create_workflow_state("wf-r5", sample_workflow)
        state.steps[0].state = StepState.COMPLETED
        state.steps[1].state = StepState.SKIPPED
        assert find_resume_step(state) == 2

    def test_resume_roundtrip_via_disk(self, state_dir, sample_workflow):
        """Simulate: run step 0, fail step 1, save, load, find resume point."""
        state = create_workflow_state("wf-resume", sample_workflow)
        state.status = "running"

        # Step 0 completes
        state.steps[0].state = StepState.COMPLETED
        state.steps[0].result = {"output": "ok", "status": "success"}
        state.steps[0].completed_at = time.time()

        # Step 1 fails
        state.steps[1].state = StepState.FAILED
        state.steps[1].error = "adapter timeout"
        state.steps[1].completed_at = time.time()
        state.steps[1].retry_count = 1

        state.status = "failed"
        save_workflow_state(state, state_dir=state_dir)

        # Reload and find resume point
        loaded = load_workflow_state("wf-resume", state_dir=state_dir)
        assert loaded is not None
        idx = find_resume_step(loaded)
        assert idx == 1
        assert loaded.steps[0].state == StepState.COMPLETED
        assert loaded.steps[1].state == StepState.FAILED
        assert loaded.steps[1].retry_count == 1


class TestFreshWorkflowNoPersistedState:
    """Test fresh workflow has no persisted state."""

    def test_no_state_dir(self, tmp_path):
        nonexistent = tmp_path / "nonexistent"
        result = load_workflow_state("any-id", state_dir=nonexistent)
        assert result is None

    def test_empty_state_dir(self, state_dir):
        state_dir.mkdir(parents=True, exist_ok=True)
        result = load_workflow_state("any-id", state_dir=state_dir)
        assert result is None

    def test_create_workflow_state_defaults(self, sample_workflow):
        state = create_workflow_state("fresh-01", sample_workflow)
        assert state.workflow_id == "fresh-01"
        assert state.workflow_name == "test-pipeline"
        assert state.original_task == ""
        assert state.status == "pending"
        assert state.current_step == 0
        assert state.created_at > 0
        assert len(state.steps) == 3
        for s in state.steps:
            assert s.state == StepState.PENDING
            assert s.result is None
            assert s.error is None

    def test_create_workflow_state_preserves_original_task(self, sample_workflow):
        state = create_workflow_state(
            "fresh-02",
            sample_workflow,
            original_task="ship the patch",
        )
        assert state.original_task == "ship the patch"


class TestListWorkflows:
    """Test listing persisted workflow states."""

    def test_list_empty(self, state_dir):
        result = list_workflow_states(state_dir=state_dir)
        assert result == []

    def test_list_nonexistent_dir(self, tmp_path):
        result = list_workflow_states(state_dir=tmp_path / "nope")
        assert result == []

    def test_list_multiple(self, state_dir, sample_workflow):
        s1 = create_workflow_state("wf-a", sample_workflow)
        s1.status = "completed"
        save_workflow_state(s1, state_dir=state_dir)

        s2 = create_workflow_state("wf-b", sample_workflow)
        s2.status = "failed"
        save_workflow_state(s2, state_dir=state_dir)

        result = list_workflow_states(state_dir=state_dir)
        assert len(result) == 2
        ids = {s.workflow_id for s in result}
        assert ids == {"wf-a", "wf-b"}

    def test_list_skips_corrupt_files(self, state_dir, sample_workflow):
        s1 = create_workflow_state("wf-good", sample_workflow)
        save_workflow_state(s1, state_dir=state_dir)

        bad = state_dir / "bad.json"
        bad.write_text("{invalid json")

        result = list_workflow_states(state_dir=state_dir)
        assert len(result) == 1
        assert result[0].workflow_id == "wf-good"
