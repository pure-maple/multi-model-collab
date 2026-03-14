"""Reusable collaboration patterns for multi-agent interaction.

Each pattern defines:
  - Roles and their provider assignments
  - Round structure (who goes when)
  - Output schema requirements per role
  - Convergence criteria specific to the pattern
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RoleSpec:
    """Specification for one role in a collaboration pattern."""

    name: str = ""
    description: str = ""
    preferred_provider: str = ""  # empty = auto-select
    instruction_template: str = ""
    output_hint: str = ""  # guidance for output structure


@dataclass
class RoundSpec:
    """One round in a pattern's execution plan."""

    roles: list[str] = field(default_factory=list)  # which roles participate
    parallel: bool = False  # True = roles run concurrently
    instruction_override: str = ""  # if set, overrides role's template


@dataclass
class CollaborationPattern:
    """A reusable template for multi-agent collaboration."""

    name: str = ""
    description: str = ""
    roles: dict[str, RoleSpec] = field(default_factory=dict)
    rounds: list[RoundSpec] = field(default_factory=list)
    max_iterations: int = 3  # how many times the round cycle can repeat
    convergence_hint: str = ""  # pattern-specific convergence guidance


# ---------------------------------------------------------------------------
# Built-in Patterns
# ---------------------------------------------------------------------------

REVIEW_PATTERN = CollaborationPattern(
    name="review",
    description=(
        "Implement → Review → Revise loop. "
        "One agent produces work, another reviews it, "
        "and the first agent revises based on feedback. "
        "Loops until the reviewer approves or max iterations reached."
    ),
    roles={
        "implementer": RoleSpec(
            name="implementer",
            description="Produces the initial implementation or revision.",
            preferred_provider="codex",
            instruction_template=(
                "Implement the following task. Produce clean, working code "
                "or a complete solution.\n\n{task}"
            ),
            output_hint="Provide your complete implementation.",
        ),
        "reviewer": RoleSpec(
            name="reviewer",
            description=(
                "Reviews the implementation for correctness, edge cases, "
                "security, and quality. Lists specific issues."
            ),
            preferred_provider="claude",
            instruction_template=(
                "Review the implementer's output. Focus on:\n"
                "- Correctness and edge cases\n"
                "- Security vulnerabilities\n"
                "- Code quality and maintainability\n\n"
                "List each issue with severity (blocking/minor). "
                "If everything looks good, respond with CONVERGED."
            ),
            output_hint=(
                "List issues as: [BLOCKING] or [MINOR] followed by description. "
                "Or CONVERGED: <reason> if approved."
            ),
        ),
        "reviser": RoleSpec(
            name="reviser",
            description="Addresses reviewer feedback with targeted fixes.",
            preferred_provider="codex",
            instruction_template=(
                "The reviewer found issues in the implementation. "
                "Fix ONLY the issues listed. Do not refactor unrelated code.\n\n"
                "Reviewer's findings are in the recent turns above."
            ),
            output_hint="Provide the revised implementation addressing each issue.",
        ),
    },
    rounds=[
        RoundSpec(roles=["implementer"]),
        RoundSpec(roles=["reviewer"]),
        RoundSpec(roles=["reviser"]),
    ],
    max_iterations=3,
    convergence_hint="Converges when reviewer finds no blocking issues.",
)


CONSENSUS_PATTERN = CollaborationPattern(
    name="consensus",
    description=(
        "Multi-perspective analysis with synthesis. "
        "Multiple agents analyze from different angles in parallel, "
        "then a synthesizer merges into a unified recommendation."
    ),
    roles={
        "analyst_impl": RoleSpec(
            name="analyst_impl",
            description="Analyzes from implementation/engineering perspective.",
            preferred_provider="codex",
            instruction_template=(
                "Analyze the following from an implementation perspective. "
                "Focus on feasibility, complexity, and technical trade-offs.\n\n"
                "{task}"
            ),
            output_hint=(
                "Provide: conclusion, evidence, confidence (high/medium/low), risks."
            ),
        ),
        "analyst_design": RoleSpec(
            name="analyst_design",
            description="Analyzes from design/UX/architecture perspective.",
            preferred_provider="gemini",
            instruction_template=(
                "Analyze the following from a design and architecture perspective. "
                "Focus on user experience, scalability, and maintainability.\n\n"
                "{task}"
            ),
            output_hint=(
                "Provide: conclusion, evidence, confidence (high/medium/low), risks."
            ),
        ),
        "analyst_security": RoleSpec(
            name="analyst_security",
            description="Analyzes from security and reliability perspective.",
            preferred_provider="claude",
            instruction_template=(
                "Analyze the following from a security and reliability perspective. "
                "Focus on vulnerabilities, failure modes, and risk mitigation.\n\n"
                "{task}"
            ),
            output_hint=(
                "Provide: conclusion, evidence, confidence (high/medium/low), risks."
            ),
        ),
        "synthesizer": RoleSpec(
            name="synthesizer",
            description="Merges all perspectives into a unified recommendation.",
            preferred_provider="claude",
            instruction_template=(
                "You have received analyses from multiple perspectives. "
                "Synthesize them into:\n"
                "1. Points of consensus\n"
                "2. Points of conflict (with your resolution)\n"
                "3. Final recommendation\n"
                "4. Remaining risks\n\n"
                "If any critical conflict remains unresolvable, "
                "respond with NEEDS_INPUT: <what you need from the user>."
            ),
            output_hint="Provide a structured synthesis report.",
        ),
    },
    rounds=[
        RoundSpec(
            roles=["analyst_impl", "analyst_design", "analyst_security"],
            parallel=True,
        ),
        RoundSpec(roles=["synthesizer"]),
    ],
    max_iterations=2,
    convergence_hint="Converges after synthesis unless conflicts need resolution.",
)


DEBATE_PATTERN = CollaborationPattern(
    name="debate",
    description=(
        "Adversarial debate pattern. "
        "One agent argues FOR a position, another argues AGAINST. "
        "An arbiter synthesizes the strongest arguments into a verdict."
    ),
    roles={
        "advocate": RoleSpec(
            name="advocate",
            description="Argues in FAVOR of the proposed approach.",
            preferred_provider="codex",
            instruction_template=(
                "You are the ADVOCATE. Argue strongly FOR the following proposal. "
                "Provide concrete evidence, examples, and rebuttals to any "
                "counter-arguments from previous rounds.\n\n{task}"
            ),
            output_hint="Present numbered arguments (A1, A2, ...) with evidence.",
        ),
        "critic": RoleSpec(
            name="critic",
            description="Argues AGAINST the proposed approach.",
            preferred_provider="gemini",
            instruction_template=(
                "You are the CRITIC. Argue strongly AGAINST the following proposal. "
                "Find weaknesses, risks, and alternatives. "
                "Respond to the advocate's specific arguments by ID.\n\n{task}"
            ),
            output_hint="Present numbered arguments (C1, C2, ...) with evidence.",
        ),
        "arbiter": RoleSpec(
            name="arbiter",
            description="Judges the debate and issues a verdict.",
            preferred_provider="claude",
            instruction_template=(
                "You are the ARBITER of this debate. "
                "Review both the advocate's and critic's arguments. "
                "Issue a verdict:\n"
                "- ADOPT: the proposal should proceed\n"
                "- REJECT: the proposal should be abandoned\n"
                "- MODIFY: adopt with specific changes\n"
                "- NEEDS_INPUT: cannot decide, need user input\n\n"
                "Explain your reasoning, citing specific argument IDs."
            ),
            output_hint="Verdict + reasoning + cited argument IDs.",
        ),
    },
    rounds=[
        RoundSpec(roles=["advocate", "critic"], parallel=True),
        RoundSpec(roles=["advocate", "critic"], parallel=True),  # rebuttal round
        RoundSpec(roles=["arbiter"]),
    ],
    max_iterations=1,
    convergence_hint="Converges after arbiter issues verdict.",
)


# Registry of built-in patterns
BUILTIN_PATTERNS: dict[str, CollaborationPattern] = {
    "review": REVIEW_PATTERN,
    "consensus": CONSENSUS_PATTERN,
    "debate": DEBATE_PATTERN,
}


def get_pattern(name: str) -> CollaborationPattern | None:
    """Get a collaboration pattern by name."""
    return BUILTIN_PATTERNS.get(name)


def list_patterns() -> dict[str, dict[str, Any]]:
    """List all available patterns with metadata."""
    return {
        name: {
            "description": p.description,
            "roles": list(p.roles.keys()),
            "rounds": len(p.rounds),
            "max_iterations": p.max_iterations,
        }
        for name, p in BUILTIN_PATTERNS.items()
    }
