"""Task orchestration primitives for mux_orchestrate."""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class OrchestrateError(ValueError):
    """Raised when an orchestration action cannot be applied."""


class TaskState(str, Enum):
    """Phase 1 task lifecycle."""

    PLANNED = "planned"
    IMPLEMENTING = "implementing"
    REVIEWING = "reviewing"
    INTEGRATED = "integrated"

    def is_terminal(self) -> bool:
        return self is TaskState.INTEGRATED


@dataclass(frozen=True)
class RoleTemplate:
    """A reusable role definition for orchestration."""

    name: str
    description: str
    recommended_models: list[str]
    skills: list[str]


ROLE_TEMPLATES: dict[str, RoleTemplate] = {
    "implementer": RoleTemplate(
        name="implementer",
        description="功能实现、代码生成",
        recommended_models=["codex", "qwen3-coder-plus"],
        skills=["coding", "testing", "refactoring"],
    ),
    "reviewer": RoleTemplate(
        name="reviewer",
        description="代码审查、Bug 发现",
        recommended_models=["dashscope/kimi-k2.5", "dashscope/MiniMax-M2.5"],
        skills=["review", "security-audit", "architecture-analysis"],
    ),
    "writer": RoleTemplate(
        name="writer",
        description="文档、Release Notes、技术写作",
        recommended_models=["dashscope/qwen3.5-plus", "claude"],
        skills=["documentation", "translation", "technical-writing"],
    ),
    "planner": RoleTemplate(
        name="planner",
        description="需求分解、任务拆解",
        recommended_models=["claude", "gemini"],
        skills=["decomposition", "architecture", "planning"],
    ),
    "debugger": RoleTemplate(
        name="debugger",
        description="问题诊断、根因分析",
        recommended_models=["claude", "dashscope/kimi-k2.5"],
        skills=["debugging", "root-cause-analysis", "profiling"],
    ),
}

VALID_ACTIONS = {"plan", "assign", "status", "review", "merge"}

_DEFAULT_ROLE = "implementer"
_ROLE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("writer", ("doc", "docs", "文档", "release note", "写作", "翻译")),
    ("planner", ("plan", "规划", "方案", "设计", "spec", "拆解")),
    ("debugger", ("debug", "bug", "fix", "排查", "诊断", "根因")),
    ("reviewer", ("review", "审查", "audit", "安全")),
)


@dataclass
class OrchestratedTask:
    """A persisted orchestration record."""

    task_id: str
    title: str
    description: str
    state: TaskState = TaskState.PLANNED
    role: str = ""
    agent: str = ""
    branch: str = ""
    suggested_role: str = _DEFAULT_ROLE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)

    def add_event(self, action: str, **details: Any) -> None:
        """Append a lifecycle event and refresh timestamps."""
        now = time.time()
        self.updated_at = now
        event = {
            "action": action,
            "state": self.state.value,
            "at": now,
        }
        for key, value in details.items():
            if value not in ("", None):
                event[key] = value
        self.events.append(event)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrchestratedTask:
        raw_state = data.get("state", TaskState.PLANNED.value)
        try:
            state = TaskState(raw_state)
        except ValueError:
            state = TaskState.PLANNED

        return cls(
            task_id=str(data.get("task_id", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            state=state,
            role=str(data.get("role", "")),
            agent=str(data.get("agent", "")),
            branch=str(data.get("branch", "")),
            suggested_role=str(data.get("suggested_role", _DEFAULT_ROLE)),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            events=list(data.get("events", [])),
        )


def available_roles() -> dict[str, dict[str, Any]]:
    """Return role metadata in JSON-friendly shape."""
    return {
        name: {
            "description": role.description,
            "recommended_models": role.recommended_models,
            "skills": role.skills,
        }
        for name, role in ROLE_TEMPLATES.items()
    }


def infer_role(task: str) -> str:
    """Guess the best role template for a task description."""
    lowered = task.casefold()
    for role, hints in _ROLE_HINTS:
        if any(hint in lowered for hint in hints):
            return role
    return _DEFAULT_ROLE


def normalize_action(action: str) -> str:
    """Validate and normalize an action string."""
    normalized = action.strip().lower()
    if normalized not in VALID_ACTIONS:
        allowed = ", ".join(sorted(VALID_ACTIONS))
        raise OrchestrateError(f"Unknown action '{action}'. Available: {allowed}")
    return normalized


def summarize_task(task: str, max_len: int = 80) -> str:
    """Generate a compact title from a free-form task description."""
    cleaned = re.sub(r"\s+", " ", task).strip()
    if not cleaned:
        raise OrchestrateError("task is required")
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def create_task(task: str, task_id: str) -> OrchestratedTask:
    """Create a planned orchestration task."""
    if not task_id.strip():
        raise OrchestrateError("task_id is required")

    entry = OrchestratedTask(
        task_id=task_id.strip(),
        title=summarize_task(task),
        description=task.strip(),
        state=TaskState.PLANNED,
        suggested_role=infer_role(task),
    )
    entry.add_event("plan", suggested_role=entry.suggested_role)
    return entry


def apply_action(
    task: OrchestratedTask,
    action: str,
    *,
    role: str = "",
    agent: str = "",
    branch: str = "",
) -> OrchestratedTask:
    """Apply a lifecycle action to an orchestration task."""
    normalized = normalize_action(action)

    if normalized == "status":
        return task

    if normalized == "assign":
        if task.state is TaskState.INTEGRATED:
            raise OrchestrateError("Integrated tasks cannot be reassigned")
        if not role.strip():
            raise OrchestrateError("role is required for assign")
        if role not in ROLE_TEMPLATES:
            available = ", ".join(sorted(ROLE_TEMPLATES))
            raise OrchestrateError(f"Unknown role '{role}'. Available: {available}")
        if not agent.strip():
            raise OrchestrateError("agent is required for assign")

        task.state = TaskState.IMPLEMENTING
        task.role = role
        task.agent = agent.strip()
        if branch.strip():
            task.branch = branch.strip()
        task.add_event("assign", role=task.role, agent=task.agent, branch=task.branch)
        return task

    if normalized == "review":
        if task.state.is_terminal():
            raise OrchestrateError("Integrated tasks cannot be reviewed again")
        if task.state is TaskState.PLANNED:
            raise OrchestrateError("Task must be assigned before review")
        if branch.strip():
            task.branch = branch.strip()
        if not task.branch:
            raise OrchestrateError("branch is required for review")

        task.state = TaskState.REVIEWING
        task.add_event("review", branch=task.branch)
        return task

    if normalized == "merge":
        if task.state is not TaskState.REVIEWING:
            raise OrchestrateError("Task must be in reviewing state before merge")
        if branch.strip():
            task.branch = branch.strip()
        if not task.branch:
            raise OrchestrateError("branch is required for merge")

        task.state = TaskState.INTEGRATED
        task.add_event("merge", branch=task.branch)
        return task

    raise OrchestrateError(f"Action '{normalized}' is not supported in Phase 1")
