"""Collaboration Engine — the core of A2A multi-agent orchestration.

Drives iterative collaboration loops:
  1. Load pattern → plan rounds
  2. For each round: build context → dispatch to agents → collect results
  3. Evaluate convergence → continue or stop
  4. Produce final artifacts and collaboration trace

Independent of transport layer — can be called from MCP or A2A HTTP.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from modelmux.a2a import convergence
from modelmux.a2a.context import CollaborationContext
from modelmux.a2a.patterns import (
    CollaborationPattern,
    RoleSpec,
    RoundSpec,
    get_pattern,
)
from modelmux.a2a.types import (
    Artifact,
    CollaborationTask,
    ConvergenceDecision,
    Part,
    TaskState,
    Turn,
)
from modelmux.adapters.base import AdapterResult, BaseAdapter

# Type alias for adapter resolver
AdapterResolver = Callable[[str], BaseAdapter]


@dataclass
class EngineConfig:
    """Configuration for the collaboration engine."""

    workdir: str = "."
    sandbox: str = "read-only"
    timeout_per_turn: int = 300
    on_progress: Callable[[str], None] | None = None
    cancel_event: asyncio.Event | None = None


class CollaborationEngine:
    """Drives multi-agent collaboration sessions."""

    def __init__(
        self,
        get_adapter: AdapterResolver,
        config: EngineConfig | None = None,
    ) -> None:
        self._get_adapter = get_adapter
        self._config = config or EngineConfig()

    async def run(
        self,
        task: str,
        pattern_name: str,
        providers: dict[str, str] | None = None,
        max_rounds: int = 0,
        max_wall_time: int = 0,
        context_id: str = "",
    ) -> CollaborationTask:
        """Execute a full collaboration session.

        Args:
            task: The user's task/goal description.
            pattern_name: Which collaboration pattern to use.
            providers: Optional role→provider mapping override.
                e.g. {"implementer": "codex", "reviewer": "gemini"}
            max_rounds: Override pattern's max_iterations.
            max_wall_time: Override default wall time limit.
            context_id: Resume an existing context (future use).

        Returns:
            CollaborationTask with full history and artifacts.
        """
        pattern = get_pattern(pattern_name)
        if not pattern:
            collab = CollaborationTask(goal=task, pattern=pattern_name)
            collab.transition(TaskState.FAILED)
            collab.metadata["error"] = (
                f"Unknown pattern: '{pattern_name}'. "
                f"Available: review, consensus, debate"
            )
            return collab

        # Initialize task
        collab = CollaborationTask(
            goal=task,
            pattern=pattern_name,
            max_rounds=max_rounds or (pattern.max_iterations * len(pattern.rounds)),
            max_wall_time=max_wall_time or 1800,
            sandbox=self._config.sandbox,
            workdir=self._config.workdir,
        )
        if context_id:
            collab.context_id = context_id

        # Resolve provider assignments
        role_providers = self._resolve_providers(pattern, providers)
        collab.providers = list(set(role_providers.values()))

        # Initialize context
        ctx = CollaborationContext.from_task(collab)
        ctx.goal = task

        collab.transition(TaskState.WORKING)
        self._progress(f"Starting '{pattern_name}' collaboration...")

        # Track artifact hashes for stability detection
        prev_hashes: dict[str, str] | None = None

        # Main collaboration loop
        iteration = 0
        while not collab.is_terminal():
            # Check for cancellation
            if self._is_canceled():
                self._progress("Collaboration canceled")
                collab.transition(TaskState.CANCELED)
                break

            iteration += 1
            self._progress(f"Iteration {iteration}/{pattern.max_iterations}...")

            for round_idx, round_spec in enumerate(pattern.rounds):
                if collab.is_terminal() or self._is_canceled():
                    break

                turns = await self._execute_round(
                    collab=collab,
                    ctx=ctx,
                    pattern=pattern,
                    round_spec=round_spec,
                    role_providers=role_providers,
                    round_num=round_idx + 1,
                    iteration=iteration,
                )

                for turn in turns:
                    collab.turns.append(turn)
                    ctx.update_after_turn(turn, collab)

                    # Evaluate convergence after each turn
                    signal = convergence.evaluate(collab, turn, prev_hashes)
                    prev_hashes = signal.metadata.get("artifact_hashes")

                    if signal.decision == ConvergenceDecision.COMPLETE:
                        self._progress(f"Converged: {signal.reason}")
                        collab.transition(TaskState.COMPLETED)
                        break
                    elif signal.decision == ConvergenceDecision.NEEDS_INPUT:
                        self._progress(f"Input required: {signal.reason}")
                        collab.transition(TaskState.INPUT_REQUIRED)
                        break
                    elif signal.decision == ConvergenceDecision.FAILED:
                        self._progress(f"Failed: {signal.reason}")
                        collab.transition(TaskState.FAILED)
                        break

            # Handle cancellation after round
            if self._is_canceled() and not collab.is_terminal():
                self._progress("Collaboration canceled")
                collab.transition(TaskState.CANCELED)
                break

            # Check iteration limit
            if not collab.is_terminal() and iteration >= pattern.max_iterations:
                self._progress(f"Max iterations ({pattern.max_iterations}) reached")
                collab.transition(TaskState.COMPLETED)

        # Finalize
        self._build_final_artifacts(collab)
        return collab

    async def _execute_round(
        self,
        collab: CollaborationTask,
        ctx: CollaborationContext,
        pattern: CollaborationPattern,
        round_spec: RoundSpec,
        role_providers: dict[str, str],
        round_num: int,
        iteration: int,
    ) -> list[Turn]:
        """Execute one round of the collaboration."""
        roles_to_run = [
            (role_name, pattern.roles[role_name])
            for role_name in round_spec.roles
            if role_name in pattern.roles
        ]

        if round_spec.parallel and len(roles_to_run) > 1:
            # Parallel execution
            self._progress(
                f"Round {round_num}: "
                f"{', '.join(r[0] for r in roles_to_run)} (parallel)..."
            )
            tasks = [
                self._dispatch_role(
                    collab,
                    ctx,
                    role_name,
                    role_spec,
                    role_providers.get(role_name, "auto"),
                    round_spec.instruction_override,
                )
                for role_name, role_spec in roles_to_run
            ]
            turns = await asyncio.gather(*tasks)
            return list(turns)
        else:
            # Sequential execution
            turns: list[Turn] = []
            for role_name, role_spec in roles_to_run:
                self._progress(
                    f"Round {round_num}: {role_name} "
                    f"→ {role_providers.get(role_name, 'auto')}..."
                )
                turn = await self._dispatch_role(
                    collab,
                    ctx,
                    role_name,
                    role_spec,
                    role_providers.get(role_name, "auto"),
                    round_spec.instruction_override,
                )
                turns.append(turn)
                # Update context between sequential turns in same round
                ctx.update_after_turn(turn, collab)
                collab.turns.append(turn)
            # Return empty — turns already appended
            return []

    async def _dispatch_role(
        self,
        collab: CollaborationTask,
        ctx: CollaborationContext,
        role_name: str,
        role_spec: RoleSpec,
        provider: str,
        instruction_override: str = "",
    ) -> Turn:
        """Dispatch a single role's turn to a CLI provider."""
        # Build the instruction
        instruction = instruction_override or role_spec.instruction_template
        instruction = instruction.replace("{task}", collab.goal)

        # Build full prompt with context
        prompt = ctx.build_prompt(
            agent_role=role_name,
            role_description=role_spec.description,
            current_instruction=instruction,
            task=collab,
            output_schema=role_spec.output_hint,
        )

        # Dispatch via adapter
        adapter = self._get_adapter(provider)
        start = time.monotonic()

        result: AdapterResult = await adapter.run(
            prompt=prompt,
            workdir=self._config.workdir,
            sandbox=self._config.sandbox,
            timeout=self._config.timeout_per_turn,
        )

        duration = time.monotonic() - start

        # Build turn record
        turn = Turn(
            provider=provider,
            role=role_name,
            prompt_summary=instruction[:200],
            output=result.output or result.error or "",
            output_summary=result.summary,
            status=result.status,
            duration_seconds=round(duration, 1),
            metadata={
                "run_id": result.run_id,
                "session_id": result.session_id,
            },
        )

        # Extract artifacts from output if present
        artifacts = self._extract_artifacts(result.output, role_name)
        turn.artifacts = artifacts
        collab.artifacts.extend(artifacts)

        return turn

    def _resolve_providers(
        self,
        pattern: CollaborationPattern,
        overrides: dict[str, str] | None,
    ) -> dict[str, str]:
        """Resolve role → provider mapping."""
        mapping: dict[str, str] = {}
        for role_name, role_spec in pattern.roles.items():
            if overrides and role_name in overrides:
                mapping[role_name] = overrides[role_name]
            elif role_spec.preferred_provider:
                mapping[role_name] = role_spec.preferred_provider
            else:
                mapping[role_name] = "codex"  # default fallback
        return mapping

    def _extract_artifacts(
        self,
        output: str,
        role_name: str,
    ) -> list[Artifact]:
        """Extract structured artifacts from agent output.

        Looks for code blocks and named sections.
        """
        artifacts: list[Artifact] = []

        # Extract fenced code blocks as artifacts
        import re

        code_blocks = re.findall(r"```(\w*)\n(.*?)```", output, re.DOTALL)
        for i, (lang, code) in enumerate(code_blocks):
            if len(code.strip()) > 50:  # skip trivial blocks
                artifacts.append(
                    Artifact(
                        name=f"{role_name}_code_{i}",
                        parts=[
                            Part(
                                text=code.strip(),
                                mime_type=f"text/x-{lang}" if lang else "text/plain",
                            )
                        ],
                        metadata={"language": lang, "role": role_name},
                    )
                )

        return artifacts

    def _build_final_artifacts(self, collab: CollaborationTask) -> None:
        """Build summary artifacts from the completed collaboration."""
        # Collaboration trace artifact
        trace_lines = []
        for t in collab.turns:
            status = "✓" if t.status == "success" else "✗"
            trace_lines.append(
                f"{status} [{t.role}/{t.provider}] "
                f"({t.duration_seconds}s): {t.output_summary or t.output[:100]}"
            )

        collab.artifacts.append(
            Artifact(
                name="collaboration_trace",
                parts=[Part(text="\n".join(trace_lines))],
                metadata={"type": "trace"},
            )
        )

    def _is_canceled(self) -> bool:
        """Check if cancellation has been requested."""
        if self._config.cancel_event and self._config.cancel_event.is_set():
            return True
        return False

    def _progress(self, msg: str) -> None:
        if self._config.on_progress:
            self._config.on_progress(msg)
