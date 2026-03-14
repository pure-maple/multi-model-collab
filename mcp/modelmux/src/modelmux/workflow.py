"""Workflow template engine for modelmux.

Defines multi-step dispatch pipelines that chain multiple providers.
Supports persistent step-file state for recoverable workflows (BMAD-inspired).

Workflow definitions live in config (profiles.toml):

    [workflows.code-review]
    description = "代码审查流水线"

    [[workflows.code-review.steps]]
    name = "implement"
    provider = "codex"
    task = "实现: {input}"

    [[workflows.code-review.steps]]
    name = "review"
    provider = "claude"
    task = "审查以下代码:\\n{implement}"
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default persistence directory
WORKFLOW_STATE_DIR = Path.home() / ".config" / "modelmux" / "workflows"


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PersistentStep:
    """Tracks execution state for a single workflow step."""

    name: str
    state: StepState = StepState.PENDING
    result: dict | None = None
    error: str | None = None
    started_at: float = 0.0
    completed_at: float = 0.0
    retry_count: int = 0


@dataclass
class WorkflowState:
    """Full persistent state for a workflow execution."""

    workflow_id: str
    workflow_name: str
    steps: list[PersistentStep]
    current_step: int = 0
    status: str = "pending"  # pending/running/completed/failed/paused
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class WorkflowStep:
    """A single step in a workflow pipeline."""

    name: str = ""
    provider: str = "auto"
    task: str = ""  # Template with {input} and {step_name} placeholders
    sandbox: str = "read-only"
    timeout: int = 300
    model: str = ""


@dataclass
class Workflow:
    """A complete workflow definition."""

    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)


# Placeholder pattern: {input} or {step_name}
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def render_task(template: str, context: dict[str, str]) -> str:
    """Render a task template by substituting placeholders.

    Placeholders:
      {input} — the original user input
      {step_name} — output from a previous step
    """

    def _replace(m: re.Match) -> str:
        key = m.group(1)
        return context.get(key, m.group(0))

    return _PLACEHOLDER_RE.sub(_replace, template)


def parse_workflows(data: dict[str, Any]) -> dict[str, Workflow]:
    """Parse workflow definitions from config data."""
    workflows: dict[str, Workflow] = {}

    raw = data.get("workflows", {})
    if not isinstance(raw, dict):
        return workflows

    for wf_name, wf_data in raw.items():
        if not isinstance(wf_data, dict):
            continue

        wf = Workflow(
            name=wf_name,
            description=wf_data.get("description", ""),
        )

        for step_data in wf_data.get("steps", []):
            if not isinstance(step_data, dict):
                continue
            step = WorkflowStep(
                name=step_data.get("name", ""),
                provider=step_data.get("provider", "auto"),
                task=step_data.get("task", ""),
                sandbox=step_data.get("sandbox", "read-only"),
                timeout=step_data.get("timeout", 300),
                model=step_data.get("model", ""),
            )
            if step.name and step.task:
                wf.steps.append(step)

        if wf.steps:
            workflows[wf_name] = wf

    return workflows


# Built-in workflow templates
BUILTIN_WORKFLOWS: dict[str, Workflow] = {
    "review": Workflow(
        name="review",
        description="Code review pipeline: implement then review",
        steps=[
            WorkflowStep(
                name="implement",
                provider="codex",
                task="{input}",
            ),
            WorkflowStep(
                name="review",
                provider="claude",
                task=(
                    "Review the following code for bugs, security issues, "
                    "and improvements:\n\n{implement}"
                ),
            ),
        ],
    ),
    "consensus": Workflow(
        name="consensus",
        description="Get opinions from multiple models then synthesize",
        steps=[
            WorkflowStep(
                name="opinion_a",
                provider="codex",
                task="{input}",
            ),
            WorkflowStep(
                name="opinion_b",
                provider="gemini",
                task="{input}",
            ),
            WorkflowStep(
                name="synthesis",
                provider="claude",
                task=(
                    "Two AI models gave different responses to the same "
                    "question. Synthesize the best answer:\n\n"
                    "--- Model A (Codex) ---\n{opinion_a}\n\n"
                    "--- Model B (Gemini) ---\n{opinion_b}\n\n"
                    "Provide a unified, best-of-both response."
                ),
            ),
        ],
    ),
}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _step_to_dict(step: PersistentStep) -> dict:
    """Serialize a PersistentStep to a JSON-safe dict."""
    d = asdict(step)
    d["state"] = step.state.value
    return d


def _step_from_dict(d: dict) -> PersistentStep:
    """Deserialize a PersistentStep from a dict."""
    return PersistentStep(
        name=d["name"],
        state=StepState(d.get("state", "pending")),
        result=d.get("result"),
        error=d.get("error"),
        started_at=d.get("started_at", 0.0),
        completed_at=d.get("completed_at", 0.0),
        retry_count=d.get("retry_count", 0),
    )


def _state_to_dict(state: WorkflowState) -> dict:
    """Serialize a WorkflowState to a JSON-safe dict."""
    return {
        "workflow_id": state.workflow_id,
        "workflow_name": state.workflow_name,
        "steps": [_step_to_dict(s) for s in state.steps],
        "current_step": state.current_step,
        "status": state.status,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }


def _state_from_dict(d: dict) -> WorkflowState:
    """Deserialize a WorkflowState from a dict."""
    return WorkflowState(
        workflow_id=d["workflow_id"],
        workflow_name=d["workflow_name"],
        steps=[_step_from_dict(s) for s in d.get("steps", [])],
        current_step=d.get("current_step", 0),
        status=d.get("status", "pending"),
        created_at=d.get("created_at", 0.0),
        updated_at=d.get("updated_at", 0.0),
    )


def save_workflow_state(
    state: WorkflowState,
    state_dir: Path | None = None,
) -> Path:
    """Persist a WorkflowState to disk as JSON.

    Returns the path of the written file.
    """
    base = state_dir or WORKFLOW_STATE_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{state.workflow_id}.json"
    state.updated_at = time.time()
    path.write_text(json.dumps(_state_to_dict(state), indent=2, ensure_ascii=False))
    return path


def load_workflow_state(
    workflow_id: str,
    state_dir: Path | None = None,
) -> WorkflowState | None:
    """Load a persisted WorkflowState from disk, or None if not found."""
    base = state_dir or WORKFLOW_STATE_DIR
    path = base / f"{workflow_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return _state_from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to load workflow state %s: %s", path, exc)
        return None


def list_workflow_states(
    state_dir: Path | None = None,
) -> list[WorkflowState]:
    """List all persisted workflow states."""
    base = state_dir or WORKFLOW_STATE_DIR
    if not base.exists():
        return []
    states: list[WorkflowState] = []
    for path in sorted(base.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            states.append(_state_from_dict(data))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Skipping invalid workflow state %s: %s", path, exc)
    return states


def create_workflow_state(
    workflow_id: str,
    workflow: Workflow,
) -> WorkflowState:
    """Create a fresh WorkflowState from a Workflow definition."""
    now = time.time()
    return WorkflowState(
        workflow_id=workflow_id,
        workflow_name=workflow.name,
        steps=[PersistentStep(name=s.name) for s in workflow.steps],
        current_step=0,
        status="pending",
        created_at=now,
        updated_at=now,
    )


def find_resume_step(state: WorkflowState) -> int:
    """Find the index of the first non-completed step to resume from.

    Returns -1 if all steps are completed.
    """
    for i, step in enumerate(state.steps):
        if step.state not in (StepState.COMPLETED, StepState.SKIPPED):
            return i
    return -1
