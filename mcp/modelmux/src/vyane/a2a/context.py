"""Context accumulation for multi-turn collaboration.

Implements the layered memory strategy:
  1. Pinned facts (goal, constraints, acceptance criteria)
  2. Rolling summary (compressed history of earlier turns)
  3. Recent raw window (last 1-2 turns in full)
  4. Artifact index (hash + summary of produced outputs)

This ensures CLI agents get rich context without blowing token limits.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from vyane.a2a.types import Artifact, CollaborationTask, Turn

# Rough token estimation: chars / 4
_CHARS_PER_TOKEN = 4

# Default budget for context section of prompt
DEFAULT_CONTEXT_BUDGET = 8000  # tokens


@dataclass
class ArtifactRef:
    """Lightweight reference to an artifact for the context index."""

    artifact_id: str = ""
    name: str = ""
    summary: str = ""
    content_hash: str = ""
    size_chars: int = 0
    turn_id: str = ""


@dataclass
class CollaborationContext:
    """Manages layered context for a collaboration session."""

    # Pinned facts (never trimmed)
    goal: str = ""
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: str = ""

    # Rolling summary (compressed older turns)
    rolling_summary: str = ""

    # Artifact index
    artifact_refs: list[ArtifactRef] = field(default_factory=list)

    # Configuration
    recent_window_size: int = 2
    context_budget_tokens: int = DEFAULT_CONTEXT_BUDGET

    @classmethod
    def from_task(cls, task: CollaborationTask) -> CollaborationContext:
        """Initialize context from a collaboration task."""
        ctx = cls(
            goal=task.goal,
            constraints=task.constraints,
        )
        # Index any existing artifacts
        for art in task.artifacts:
            ctx._index_artifact(art, turn_id="initial")
        return ctx

    def build_prompt(
        self,
        agent_role: str,
        role_description: str,
        current_instruction: str,
        task: CollaborationTask,
        output_schema: str = "",
    ) -> str:
        """Build a complete prompt with layered context.

        Structure:
          1. Role assignment
          2. Shared goal / acceptance criteria
          3. Pinned constraints
          4. Collaboration summary (rolling)
          5. Recent turns (raw)
          6. Artifact index
          7. Current instruction
          8. Output format requirements
        """
        sections: list[str] = []

        # 1. Role
        sections.append(
            f"## Your Role\n"
            f"You are acting as **{agent_role}** in a multi-agent collaboration.\n"
            f"{role_description}"
        )

        # 2. Goal
        sections.append(f"## Shared Goal\n{self.goal}")
        if self.acceptance_criteria:
            sections.append(f"## Acceptance Criteria\n{self.acceptance_criteria}")

        # 3. Constraints
        if self.constraints:
            constraints_text = "\n".join(f"- {c}" for c in self.constraints)
            sections.append(f"## Constraints\n{constraints_text}")

        # 4. Rolling summary
        if self.rolling_summary:
            sections.append(f"## Collaboration Progress So Far\n{self.rolling_summary}")

        # 5. Recent turns (full text, last N)
        recent = task.turns[-self.recent_window_size :]
        if recent:
            turns_text = []
            for t in recent:
                header = f"**[{t.role}] ({t.provider})** (turn {t.turn_id}):"
                # Use summary if output is too long
                content = t.output
                if len(content) > 3000:
                    content = t.output_summary or content[:3000] + "\n...[truncated]"
                turns_text.append(f"{header}\n{content}")
            sections.append(
                "## Recent Agent Outputs\n" + "\n\n---\n\n".join(turns_text)
            )

        # 6. Artifact index
        if self.artifact_refs:
            art_lines = []
            for ref in self.artifact_refs:
                art_lines.append(
                    f"- **{ref.name}** (id: {ref.artifact_id}, "
                    f"{ref.size_chars} chars, hash: {ref.content_hash[:8]}): "
                    f"{ref.summary}"
                )
            sections.append("## Shared Artifacts\n" + "\n".join(art_lines))

        # 7. Current instruction
        sections.append(f"## Your Task This Round\n{current_instruction}")

        # 8. Output schema
        if output_schema:
            sections.append(f"## Required Output Format\n{output_schema}")

        # Convergence hint
        sections.append(
            "## Convergence\n"
            "If you believe the work is complete and meets all criteria, "
            "include `CONVERGED: <reason>` at the start of your response. "
            "If there are unresolved issues, list them clearly."
        )

        return "\n\n".join(sections)

    def update_after_turn(self, turn: Turn, task: CollaborationTask) -> None:
        """Update context state after a turn completes."""
        # Index new artifacts
        for art in turn.artifacts:
            self._index_artifact(art, turn_id=turn.turn_id)

        # Update rolling summary if we've exceeded the recent window
        older_turns = task.turns[: -self.recent_window_size]
        summary_lines = len(self.rolling_summary.split("\n"))
        if older_turns and len(older_turns) > summary_lines // 2:
            self.rolling_summary = self._compress_turns(older_turns)

    def _compress_turns(self, turns: list[Turn]) -> str:
        """Compress older turns into a rolling summary.

        Uses structured extraction rather than LLM summarization
        to keep it fast and deterministic.
        """
        lines: list[str] = []
        for t in turns:
            summary = t.output_summary or t.output[:200]
            status_marker = "✓" if t.status == "success" else "✗"
            lines.append(
                f"- Round {t.turn_id} [{t.role}/{t.provider}] {status_marker}: "
                f"{summary}"
            )
        return "\n".join(lines)

    def _index_artifact(self, artifact: Artifact, turn_id: str) -> None:
        """Add or update an artifact in the index."""
        content = "".join(p.text for p in artifact.parts)
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Check if this artifact already exists (update)
        for ref in self.artifact_refs:
            if ref.artifact_id == artifact.artifact_id:
                ref.content_hash = content_hash
                ref.size_chars = len(content)
                ref.turn_id = turn_id
                return

        self.artifact_refs.append(
            ArtifactRef(
                artifact_id=artifact.artifact_id,
                name=artifact.name or artifact.artifact_id,
                summary=content[:150].replace("\n", " "),
                content_hash=content_hash,
                size_chars=len(content),
                turn_id=turn_id,
            )
        )

    def estimate_tokens(self, task: CollaborationTask) -> int:
        """Estimate total context size in tokens."""
        # Rough estimate of what build_prompt would produce
        base = len(self.goal) + sum(len(c) for c in self.constraints)
        summary = len(self.rolling_summary)
        recent = sum(len(t.output) for t in task.turns[-self.recent_window_size :])
        artifacts = sum(len(r.summary) for r in self.artifact_refs)
        return (base + summary + recent + artifacts) // _CHARS_PER_TOKEN
