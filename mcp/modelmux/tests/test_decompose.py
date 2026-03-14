"""Tests for task decomposition module."""

import json

from vyane.decompose import (
    DecompositionPlan,
    Subtask,
    build_merge_prompt,
    parse_decomposition,
)


class TestParseDecomposition:
    def test_simple_json(self):
        response = json.dumps(
            {
                "should_decompose": True,
                "subtasks": [
                    {
                        "name": "backend",
                        "task": "Implement REST API endpoints",
                        "provider": "codex",
                        "depends_on": [],
                    },
                    {
                        "name": "frontend",
                        "task": "Create React UI components",
                        "provider": "gemini",
                        "depends_on": [],
                    },
                    {
                        "name": "review",
                        "task": "Review the implementation",
                        "provider": "claude",
                        "depends_on": ["backend", "frontend"],
                    },
                ],
            }
        )
        plan = parse_decomposition(response)
        assert plan.should_decompose is True
        assert len(plan.subtasks) == 3
        assert plan.subtasks[0].name == "backend"
        assert plan.subtasks[0].provider == "codex"
        assert plan.subtasks[2].depends_on == ["backend", "frontend"]

    def test_json_in_code_fence(self):
        response = """Here's the decomposition plan:
```json
{
  "should_decompose": true,
  "subtasks": [
    {"name": "analysis", "task": "Analyze code", "provider": "claude"},
    {"name": "fix", "task": "Fix bugs", "provider": "codex"}
  ]
}
```
"""
        plan = parse_decomposition(response)
        assert plan.should_decompose is True
        assert len(plan.subtasks) == 2

    def test_no_decompose(self):
        response = json.dumps(
            {
                "should_decompose": False,
                "subtasks": [
                    {"name": "single", "task": "Do the thing", "provider": "auto"}
                ],
            }
        )
        plan = parse_decomposition(response)
        assert plan.should_decompose is False

    def test_single_subtask_forces_no_decompose(self):
        response = json.dumps(
            {
                "should_decompose": True,
                "subtasks": [
                    {"name": "only_one", "task": "Simple task", "provider": "codex"}
                ],
            }
        )
        plan = parse_decomposition(response)
        assert plan.should_decompose is False

    def test_invalid_json(self):
        plan = parse_decomposition("This is not JSON at all")
        assert plan.should_decompose is False
        assert len(plan.subtasks) == 0

    def test_missing_fields_skipped(self):
        response = json.dumps(
            {
                "should_decompose": True,
                "subtasks": [
                    {"name": "good", "task": "Valid subtask", "provider": "codex"},
                    {"name": "", "task": "Missing name"},
                    {"task": "No name field"},
                    {"name": "no_task"},
                ],
            }
        )
        plan = parse_decomposition(response)
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].name == "good"
        # Only 1 valid subtask, so should_decompose forced False
        assert plan.should_decompose is False

    def test_default_provider(self):
        response = json.dumps(
            {
                "should_decompose": True,
                "subtasks": [
                    {"name": "a", "task": "Task A"},
                    {"name": "b", "task": "Task B"},
                ],
            }
        )
        plan = parse_decomposition(response)
        assert plan.subtasks[0].provider == "auto"
        assert plan.subtasks[1].provider == "auto"


class TestDecompositionPlan:
    def test_is_parallel_all_independent(self):
        plan = DecompositionPlan(
            should_decompose=True,
            subtasks=[
                Subtask(name="a", task="A"),
                Subtask(name="b", task="B"),
            ],
        )
        assert plan.is_parallel is True

    def test_is_parallel_with_deps(self):
        plan = DecompositionPlan(
            should_decompose=True,
            subtasks=[
                Subtask(name="a", task="A"),
                Subtask(name="b", task="B", depends_on=["a"]),
            ],
        )
        assert plan.is_parallel is False

    def test_execution_order_parallel(self):
        plan = DecompositionPlan(
            should_decompose=True,
            subtasks=[
                Subtask(name="a", task="A"),
                Subtask(name="b", task="B"),
                Subtask(name="c", task="C"),
            ],
        )
        waves = plan.execution_order()
        assert len(waves) == 1
        assert len(waves[0]) == 3

    def test_execution_order_sequential(self):
        plan = DecompositionPlan(
            should_decompose=True,
            subtasks=[
                Subtask(name="a", task="A"),
                Subtask(name="b", task="B", depends_on=["a"]),
                Subtask(name="c", task="C", depends_on=["b"]),
            ],
        )
        waves = plan.execution_order()
        assert len(waves) == 3
        assert waves[0][0].name == "a"
        assert waves[1][0].name == "b"
        assert waves[2][0].name == "c"

    def test_execution_order_mixed(self):
        plan = DecompositionPlan(
            should_decompose=True,
            subtasks=[
                Subtask(name="impl_be", task="Backend"),
                Subtask(name="impl_fe", task="Frontend"),
                Subtask(name="review", task="Review", depends_on=["impl_be", "impl_fe"]),
            ],
        )
        waves = plan.execution_order()
        assert len(waves) == 2
        assert len(waves[0]) == 2  # impl_be + impl_fe in parallel
        assert waves[1][0].name == "review"

    def test_execution_order_empty(self):
        plan = DecompositionPlan(should_decompose=False, subtasks=[])
        assert plan.execution_order() == []

    def test_execution_order_circular_deps(self):
        plan = DecompositionPlan(
            should_decompose=True,
            subtasks=[
                Subtask(name="a", task="A", depends_on=["b"]),
                Subtask(name="b", task="B", depends_on=["a"]),
            ],
        )
        waves = plan.execution_order()
        # Should still complete (force remaining into one wave)
        assert len(waves) == 1
        assert len(waves[0]) == 2


class TestBuildMergePrompt:
    def test_basic_merge(self):
        prompt = build_merge_prompt(
            "Build a web app",
            {"backend": "REST API code here", "frontend": "React components here"},
        )
        assert "Build a web app" in prompt
        assert "backend" in prompt
        assert "REST API code here" in prompt
        assert "frontend" in prompt
        assert "React components here" in prompt
        assert "Combine" in prompt
