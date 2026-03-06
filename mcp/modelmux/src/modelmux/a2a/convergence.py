"""Multi-tier convergence detection for collaboration sessions.

Layers (evaluated in order, first decisive result wins):
  1. Hard limits (max rounds, max wall time)
  2. Structured signals (explicit CONVERGED/blocking markers in output)
  3. Stability detection (artifact hash unchanged across rounds)
  4. LLM judge (fallback for ambiguous cases — expensive, used sparingly)
"""

from __future__ import annotations

import hashlib
import re

from modelmux.a2a.types import (
    CollaborationTask,
    ConvergenceDecision,
    ConvergenceSignal,
    Turn,
)

# Patterns indicating explicit convergence
_CONVERGED_PATTERNS = [
    re.compile(r"^CONVERGED:\s*(.+)", re.MULTILINE | re.IGNORECASE),
    re.compile(r"\bLGTM\b", re.IGNORECASE),
    re.compile(r"\bAPPROVED\b", re.IGNORECASE),
    re.compile(r"no\s+(remaining\s+)?issues?\s+found", re.IGNORECASE),
]

# Patterns indicating unresolved issues
_BLOCKING_PATTERNS = [
    re.compile(
        r"(?:blocking|critical|major)\s+(?:issue|problem|bug|concern)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:must|need(?:s)?|should)\s+(?:fix|address|resolve)", re.IGNORECASE),
]


def evaluate(
    task: CollaborationTask,
    latest_turn: Turn,
    previous_artifact_hashes: dict[str, str] | None = None,
) -> ConvergenceSignal:
    """Evaluate whether a collaboration should continue or stop.

    Args:
        task: The current collaboration task state.
        latest_turn: The most recently completed turn.
        previous_artifact_hashes: Hash of key artifacts from previous round
            for stability detection.

    Returns:
        ConvergenceSignal with decision and reasoning.
    """
    # Layer 1: Hard limits
    signal = _check_hard_limits(task)
    if signal:
        return signal

    # Layer 2: Structured signals in output
    signal = _check_structured_signals(latest_turn)
    if signal:
        return signal

    # Layer 3: Stability detection
    current_hashes = _compute_artifact_hashes(task)
    if previous_artifact_hashes:
        signal = _check_stability(current_hashes, previous_artifact_hashes)
        if signal:
            signal.metadata["artifact_hashes"] = current_hashes
            return signal

    # Default: continue
    return ConvergenceSignal(
        decision=ConvergenceDecision.CONTINUE,
        reason=f"Round {task.round_count} complete, no convergence signals detected",
        metadata={"artifact_hashes": current_hashes},
    )


def _check_hard_limits(task: CollaborationTask) -> ConvergenceSignal | None:
    """Layer 1: Check hard resource limits."""
    if task.round_count >= task.max_rounds:
        return ConvergenceSignal(
            decision=ConvergenceDecision.COMPLETE,
            reason=f"Reached max rounds ({task.max_rounds})",
            confidence=1.0,
        )

    if task.elapsed_seconds >= task.max_wall_time:
        return ConvergenceSignal(
            decision=ConvergenceDecision.COMPLETE,
            reason=f"Reached max wall time ({task.max_wall_time}s)",
            confidence=1.0,
        )

    # Too many consecutive failures
    recent_failures = 0
    for turn in reversed(task.turns):
        if turn.status != "success":
            recent_failures += 1
        else:
            break
    if recent_failures >= 3:
        return ConvergenceSignal(
            decision=ConvergenceDecision.FAILED,
            reason=f"{recent_failures} consecutive turn failures",
            confidence=1.0,
        )

    return None


def _check_structured_signals(turn: Turn) -> ConvergenceSignal | None:
    """Layer 2: Check for explicit convergence/blocking signals in output."""
    output = turn.output or ""

    # Check for explicit convergence
    for pattern in _CONVERGED_PATTERNS:
        match = pattern.search(output)
        if match:
            reason = match.group(1) if match.lastindex else match.group(0)
            return ConvergenceSignal(
                decision=ConvergenceDecision.COMPLETE,
                reason=f"Agent signaled convergence: {reason.strip()}",
                confidence=0.85,
            )

    # Check for explicit input-required
    if re.search(r"NEEDS_INPUT:", output, re.IGNORECASE):
        return ConvergenceSignal(
            decision=ConvergenceDecision.NEEDS_INPUT,
            reason="Agent requested additional input",
            confidence=0.9,
        )

    # Check for blocking issues (weak signal — don't decide, just annotate)
    blocking = []
    for pattern in _BLOCKING_PATTERNS:
        matches = pattern.findall(output)
        blocking.extend(matches)

    if blocking and turn.role in ("reviewer", "critic", "red_team"):
        # Reviewer found issues — definitely continue
        return ConvergenceSignal(
            decision=ConvergenceDecision.CONTINUE,
            reason=f"Reviewer found {len(blocking)} issue(s)",
            blocking_issues=blocking[:5],
            confidence=0.8,
        )

    return None


def _check_stability(
    current_hashes: dict[str, str],
    previous_hashes: dict[str, str],
) -> ConvergenceSignal | None:
    """Layer 3: Check if artifacts have stabilized (no changes)."""
    if not current_hashes or not previous_hashes:
        return None

    # Detect added or removed artifacts — not stable
    if set(current_hashes) != set(previous_hashes):
        return None

    unchanged = sum(
        1 for k in current_hashes if current_hashes[k] == previous_hashes[k]
    )

    if unchanged == len(current_hashes):
        return ConvergenceSignal(
            decision=ConvergenceDecision.COMPLETE,
            reason=(
                f"All {unchanged} artifact(s) unchanged — output has stabilized"
            ),
            confidence=0.75,
        )

    return None


def _compute_artifact_hashes(task: CollaborationTask) -> dict[str, str]:
    """Compute content hashes for all current artifacts."""
    hashes: dict[str, str] = {}
    for art in task.artifacts:
        content = "".join(p.text for p in art.parts)
        hashes[art.artifact_id] = hashlib.sha256(content.encode()).hexdigest()
    return hashes


def build_judge_prompt(task: CollaborationTask) -> str:
    """Build a prompt for the LLM judge (Layer 4).

    Called when layers 1-3 are inconclusive after several rounds.
    Returns a focused prompt that only includes essential info.
    """
    # Gather the last 2 turns summaries
    recent = task.turns[-2:] if len(task.turns) >= 2 else task.turns
    turns_summary = "\n".join(
        f"- [{t.role}/{t.provider}]: {t.output_summary or t.output[:300]}"
        for t in recent
    )

    # Count unresolved issues from latest reviewer turn
    reviewer_turns = [t for t in task.turns if t.role in ("reviewer", "critic")]
    latest_review = reviewer_turns[-1].output[:500] if reviewer_turns else "N/A"

    return (
        "You are a convergence judge for a multi-agent collaboration.\n\n"
        f"## Goal\n{task.goal}\n\n"
        f"## Rounds completed: {task.round_count}/{task.max_rounds}\n\n"
        f"## Recent turns:\n{turns_summary}\n\n"
        f"## Latest review:\n{latest_review}\n\n"
        "## Your Decision\n"
        "Reply with EXACTLY one of:\n"
        "- `CONTINUE` — if there are clear unresolved issues worth another round\n"
        "- `COMPLETE` — if the output is good enough\n"
        "- `NEEDS_INPUT` — if the goal is ambiguous and needs user clarification\n"
        "- `FAILED` — if the collaboration is stuck and not making progress\n\n"
        "Reply with your decision and a one-line reason."
    )
