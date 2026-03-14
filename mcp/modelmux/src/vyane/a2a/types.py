"""A2A data types aligned with Agent2Agent Protocol v0.3.0.

Internal model follows v1.0 RC field shapes for forward compatibility.
Serializers will adapt to whichever protocol version the client speaks.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Task State Machine
# ---------------------------------------------------------------------------


class TaskState(str, Enum):
    """A2A task lifecycle states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    AUTH_REQUIRED = "auth-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    REJECTED = "rejected"

    def is_terminal(self) -> bool:
        return self in (
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELED,
            TaskState.REJECTED,
        )

    def is_interrupted(self) -> bool:
        return self in (TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED)


# ---------------------------------------------------------------------------
# Message / Part / Artifact  (A2A canonical data model)
# ---------------------------------------------------------------------------


class MessageRole(str, Enum):
    USER = "user"
    AGENT = "agent"


@dataclass
class Part:
    """Smallest content unit within a Message or Artifact."""

    kind: str = "text"  # text | file | data
    text: str = ""
    mime_type: str = "text/plain"
    data: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """A single communication turn between client and agent."""

    role: MessageRole = MessageRole.USER
    parts: list[Part] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def text(role: MessageRole, content: str, **meta: Any) -> Message:
        return Message(
            role=role,
            parts=[Part(text=content)],
            metadata=meta,
        )


@dataclass
class Artifact:
    """A tangible output produced by agent work."""

    artifact_id: str = ""
    name: str = ""
    parts: list[Part] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id:
            self.artifact_id = f"art-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Turn — internal concept tracking each agent interaction in a collaboration
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    """One round of agent interaction within a collaboration.

    Not part of A2A spec — this is Vyane's internal tracking of
    each CLI dispatch within a collaboration session.
    """

    turn_id: str = ""
    provider: str = ""
    role: str = ""  # implementer, reviewer, reviser, advocate, critic, ...
    prompt_summary: str = ""
    output: str = ""
    output_summary: str = ""
    artifacts: list[Artifact] = field(default_factory=list)
    status: str = "success"  # success | error | timeout
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.turn_id:
            self.turn_id = f"turn-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Collaboration Task — the central stateful object
# ---------------------------------------------------------------------------


@dataclass
class CollaborationTask:
    """A multi-turn collaboration session between agents.

    Maps to A2A Task concept. One collaboration = one task with
    a defined lifecycle, context, and artifact outputs.
    """

    task_id: str = ""
    context_id: str = ""
    state: TaskState = TaskState.SUBMITTED
    pattern: str = ""  # review, consensus, debate, custom
    goal: str = ""
    constraints: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)

    # Configuration
    max_rounds: int = 5
    max_wall_time: int = 600
    sandbox: str = "read-only"
    workdir: str = "."

    # Timing
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    # Metadata for A2A extensions
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = f"task-{uuid.uuid4().hex[:8]}"
        if not self.context_id:
            self.context_id = f"ctx-{uuid.uuid4().hex[:8]}"

    def is_terminal(self) -> bool:
        return self.state.is_terminal()

    def transition(self, new_state: TaskState) -> None:
        """Transition to a new state with validation."""
        if self.state.is_terminal():
            raise ValueError(
                f"Cannot transition from terminal state {self.state.value}"
            )
        self.state = new_state
        self.updated_at = time.time()
        if new_state.is_terminal():
            self.completed_at = time.time()

    @property
    def round_count(self) -> int:
        """Number of completed collaboration rounds."""
        return len(self.turns)

    @property
    def elapsed_seconds(self) -> float:
        end = self.completed_at or time.time()
        return end - self.created_at

    @property
    def total_duration(self) -> float:
        """Sum of all turn durations."""
        return sum(t.duration_seconds for t in self.turns)


# ---------------------------------------------------------------------------
# Agent Card — capability advertisement
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    """A specific capability advertised by an agent."""

    id: str = ""
    name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


@dataclass
class AgentCard:
    """A2A Agent Card — the agent's 'business card'.

    Describes identity, capabilities, endpoint, and supported features.
    """

    name: str = "Vyane"
    description: str = (
        "Multi-model collaboration orchestrator. "
        "Routes tasks to and coordinates between AI coding agents "
        "(Codex, Gemini, Claude) with iterative feedback loops."
    )
    url: str = ""
    version: str = ""
    protocol_version: str = "0.3.0"
    skills: list[Skill] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)
    auth_schemes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "protocolVersion": self.protocol_version,
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "tags": s.tags,
                    "examples": s.examples,
                }
                for s in self.skills
            ],
            "capabilities": self.capabilities,
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain", "application/json"],
        }
        if self.auth_schemes:
            d["authSchemes"] = self.auth_schemes
        return d


# ---------------------------------------------------------------------------
# Convergence Signal — output from convergence evaluator
# ---------------------------------------------------------------------------


class ConvergenceDecision(str, Enum):
    """Result of convergence evaluation."""

    CONTINUE = "continue"
    COMPLETE = "complete"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"


@dataclass
class ConvergenceSignal:
    """Structured convergence evaluation result."""

    decision: ConvergenceDecision = ConvergenceDecision.CONTINUE
    reason: str = ""
    blocking_issues: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0-1.0
    metadata: dict[str, Any] = field(default_factory=dict)
