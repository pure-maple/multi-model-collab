"""Workflow template engine for modelmux.

Defines multi-step dispatch pipelines that chain multiple providers.

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

import re
from dataclasses import dataclass, field
from typing import Any


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
