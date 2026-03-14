"""Task decomposition for complex multi-model dispatch.

Uses a planner model to analyze complex tasks, break them into subtasks,
route each to the best-suited provider, and merge results.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

DECOMPOSE_SYSTEM_PROMPT = """\
You are a task decomposition planner for a multi-model AI system.
Analyze the given task and decide whether to decompose it into subtasks.

Available providers and their strengths:
- codex: code generation, algorithms, debugging, refactoring
- gemini: research, design, documentation, multimodal
- claude: architecture, reasoning, analysis, review
- dashscope: code review, alternative perspective (Chinese models)
- ollama: local models, privacy-sensitive tasks

Rules:
1. Only decompose if the task has 2+ genuinely distinct concerns
2. If the task is simple or focused, return a single subtask
3. Maximize parallelism — minimize dependencies between subtasks
4. Each subtask should be self-contained enough for one model to handle

Return ONLY a JSON object with this schema:
{
  "should_decompose": true/false,
  "subtasks": [
    {
      "name": "short_identifier",
      "task": "full subtask description with all needed context",
      "provider": "best_provider_name",
      "depends_on": []
    }
  ]
}"""


@dataclass
class Subtask:
    """A single subtask in a decomposition plan."""

    name: str
    task: str
    provider: str = "auto"
    depends_on: list[str] = field(default_factory=list)


@dataclass
class DecompositionPlan:
    """Result of task decomposition."""

    should_decompose: bool
    subtasks: list[Subtask]
    raw_response: str = ""

    @property
    def is_parallel(self) -> bool:
        """True if all subtasks can run in parallel (no dependencies)."""
        return all(not s.depends_on for s in self.subtasks)

    def execution_order(self) -> list[list[Subtask]]:
        """Return subtasks grouped into execution waves.

        Each wave contains subtasks that can run in parallel.
        Waves are ordered by dependency resolution.
        """
        if not self.subtasks:
            return []

        completed: set[str] = set()
        remaining = list(self.subtasks)
        waves: list[list[Subtask]] = []

        while remaining:
            wave = [s for s in remaining if all(d in completed for d in s.depends_on)]
            if not wave:
                # Circular dependency — force remaining into one wave
                wave = remaining[:]
            waves.append(wave)
            for s in wave:
                completed.add(s.name)
                remaining.remove(s)

        return waves


def parse_decomposition(response: str) -> DecompositionPlan:
    """Parse a model's decomposition response into a structured plan."""
    # Try to extract JSON from the response
    json_str = _extract_json(response)
    if not json_str:
        return DecompositionPlan(
            should_decompose=False,
            subtasks=[],
            raw_response=response,
        )

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return DecompositionPlan(
            should_decompose=False,
            subtasks=[],
            raw_response=response,
        )

    should_decompose = data.get("should_decompose", False)
    raw_subtasks = data.get("subtasks", [])

    subtasks = []
    for st in raw_subtasks:
        if not isinstance(st, dict):
            continue
        name = st.get("name", "")
        task = st.get("task", "")
        if not name or not task:
            continue
        subtasks.append(
            Subtask(
                name=name,
                task=task,
                provider=st.get("provider", "auto"),
                depends_on=st.get("depends_on", []),
            )
        )

    # If planner says decompose but only gave 1 subtask, don't decompose
    if len(subtasks) <= 1:
        should_decompose = False

    return DecompositionPlan(
        should_decompose=should_decompose,
        subtasks=subtasks,
        raw_response=response,
    )


def build_merge_prompt(
    original_task: str,
    subtask_results: dict[str, str],
) -> str:
    """Build a prompt to merge subtask results into a cohesive response."""
    parts = [
        "The following task was decomposed into subtasks and each was handled "
        "by a specialized AI model. Synthesize the results into a single, "
        "cohesive response.\n",
        f"## Original Task\n{original_task}\n",
        "## Subtask Results\n",
    ]
    for name, result in subtask_results.items():
        parts.append(f"### {name}\n{result}\n")

    parts.append(
        "\n## Instructions\n"
        "Combine the above results into a unified response. "
        "Resolve any contradictions, remove redundancy, and ensure completeness."
    )
    return "\n".join(parts)


def _extract_json(text: str) -> str | None:
    """Extract JSON object from text that may contain markdown fences."""
    # Try the whole text first
    text = text.strip()
    if text.startswith("{"):
        return text

    # Try to find JSON in code fences
    match = re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```", text, re.DOTALL)
    if match:
        return match.group(1)

    # Try to find any JSON object
    match = re.search(r"\{[^{}]*\"should_decompose\"[^{}]*\}", text, re.DOTALL)
    if match:
        return match.group(0)

    return None
