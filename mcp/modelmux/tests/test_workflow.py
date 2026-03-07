"""Tests for the workflow template engine."""

import pytest

from modelmux.workflow import (
    BUILTIN_WORKFLOWS,
    Workflow,
    WorkflowStep,
    parse_workflows,
    render_task,
)


class TestRenderTask:
    def test_simple_input(self):
        result = render_task("{input}", {"input": "hello"})
        assert result == "hello"

    def test_step_reference(self):
        result = render_task(
            "Review: {implement}",
            {"implement": "def foo(): pass"},
        )
        assert result == "Review: def foo(): pass"

    def test_multiple_placeholders(self):
        result = render_task(
            "{input} and {step1}",
            {"input": "original", "step1": "result1"},
        )
        assert result == "original and result1"

    def test_missing_placeholder_unchanged(self):
        result = render_task("{missing}", {"input": "hello"})
        assert result == "{missing}"

    def test_no_placeholders(self):
        result = render_task("plain text", {})
        assert result == "plain text"

    def test_empty_context(self):
        result = render_task("{input}", {})
        assert result == "{input}"


class TestParseWorkflows:
    def test_empty_config(self):
        workflows = parse_workflows({})
        assert workflows == {}

    def test_no_workflows_key(self):
        workflows = parse_workflows({"routing": {}})
        assert workflows == {}

    def test_single_workflow(self):
        config = {
            "workflows": {
                "test": {
                    "description": "Test workflow",
                    "steps": [
                        {
                            "name": "step1",
                            "provider": "codex",
                            "task": "{input}",
                        },
                    ],
                },
            },
        }
        workflows = parse_workflows(config)
        assert "test" in workflows
        wf = workflows["test"]
        assert wf.name == "test"
        assert wf.description == "Test workflow"
        assert len(wf.steps) == 1
        assert wf.steps[0].name == "step1"
        assert wf.steps[0].provider == "codex"

    def test_multi_step_workflow(self):
        config = {
            "workflows": {
                "pipeline": {
                    "steps": [
                        {"name": "a", "provider": "codex", "task": "{input}"},
                        {
                            "name": "b",
                            "provider": "claude",
                            "task": "Review: {a}",
                        },
                    ],
                },
            },
        }
        workflows = parse_workflows(config)
        wf = workflows["pipeline"]
        assert len(wf.steps) == 2
        assert wf.steps[1].task == "Review: {a}"

    def test_step_defaults(self):
        config = {
            "workflows": {
                "w": {
                    "steps": [
                        {"name": "s", "task": "do it"},
                    ],
                },
            },
        }
        workflows = parse_workflows(config)
        step = workflows["w"].steps[0]
        assert step.provider == "auto"
        assert step.sandbox == "read-only"
        assert step.timeout == 300
        assert step.model == ""

    def test_step_custom_settings(self):
        config = {
            "workflows": {
                "w": {
                    "steps": [
                        {
                            "name": "s",
                            "task": "do it",
                            "sandbox": "write",
                            "timeout": 60,
                            "model": "gpt-4.1-mini",
                        },
                    ],
                },
            },
        }
        workflows = parse_workflows(config)
        step = workflows["w"].steps[0]
        assert step.sandbox == "write"
        assert step.timeout == 60
        assert step.model == "gpt-4.1-mini"

    def test_skips_invalid_steps(self):
        config = {
            "workflows": {
                "w": {
                    "steps": [
                        {"name": "good", "task": "ok"},
                        {"name": "", "task": "no name"},  # no name
                        {"name": "notask"},  # no task
                        "not a dict",
                    ],
                },
            },
        }
        workflows = parse_workflows(config)
        assert len(workflows["w"].steps) == 1
        assert workflows["w"].steps[0].name == "good"

    def test_skips_empty_workflow(self):
        config = {
            "workflows": {
                "empty": {"steps": []},
            },
        }
        workflows = parse_workflows(config)
        assert "empty" not in workflows

    def test_non_dict_workflow(self):
        config = {
            "workflows": {
                "bad": "not a dict",
                "good": {
                    "steps": [{"name": "s", "task": "t"}],
                },
            },
        }
        workflows = parse_workflows(config)
        assert "bad" not in workflows
        assert "good" in workflows

    def test_non_dict_workflows_section(self):
        workflows = parse_workflows({"workflows": "invalid"})
        assert workflows == {}


class TestBuiltinWorkflows:
    def test_review_workflow_exists(self):
        assert "review" in BUILTIN_WORKFLOWS

    def test_consensus_workflow_exists(self):
        assert "consensus" in BUILTIN_WORKFLOWS

    def test_review_has_two_steps(self):
        wf = BUILTIN_WORKFLOWS["review"]
        assert len(wf.steps) == 2
        assert wf.steps[0].name == "implement"
        assert wf.steps[1].name == "review"

    def test_consensus_has_three_steps(self):
        wf = BUILTIN_WORKFLOWS["consensus"]
        assert len(wf.steps) == 3

    def test_review_uses_input_placeholder(self):
        wf = BUILTIN_WORKFLOWS["review"]
        assert "{input}" in wf.steps[0].task

    def test_review_references_previous_step(self):
        wf = BUILTIN_WORKFLOWS["review"]
        assert "{implement}" in wf.steps[1].task

    def test_consensus_references_both_opinions(self):
        wf = BUILTIN_WORKFLOWS["consensus"]
        synthesis = wf.steps[2]
        assert "{opinion_a}" in synthesis.task
        assert "{opinion_b}" in synthesis.task
