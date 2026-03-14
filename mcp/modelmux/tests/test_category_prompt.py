"""Tests for MER-93: Per-Category Prompt Append."""

from vyane.config import (
    CategoryBinding,
    MuxConfig,
    Profile,
    get_category_binding,
)
from vyane.routing import IntentCategory, IntentResult, classify_intent
from vyane.server import _DEFAULT_CATEGORY_PROMPTS


# ── Helper ──


def _apply_prompt_append(
    task: str,
    intent: IntentResult,
    binding: CategoryBinding | None,
    auto_prompt_append: bool = True,
) -> str:
    """Reproduce the MER-93 prompt-append logic from mux_dispatch."""
    # MER-89 binding prepend (already in dispatch)
    if binding and binding.prompt_template:
        task = f"[System: {binding.prompt_template}]\n\n{task}"

    # MER-93 default prompt append
    if (
        auto_prompt_append
        and intent.confidence >= 0.3
        and not (binding and binding.prompt_template)
    ):
        cat_prompt = _DEFAULT_CATEGORY_PROMPTS.get(intent.primary.value, "")
        if cat_prompt:
            task = f"{task}\n\n[Guidance: {cat_prompt}]"

    return task


# ── Default prompts applied for each category ──


def test_default_prompts_exist_for_all_categories():
    """Every IntentCategory has a default prompt snippet."""
    for cat in IntentCategory:
        assert cat.value in _DEFAULT_CATEGORY_PROMPTS, (
            f"Missing default prompt for {cat.value}"
        )


def test_default_prompt_applied_code_gen():
    """Default prompt is appended for code-gen intent."""
    intent = IntentResult(
        primary=IntentCategory.CODE_GEN, confidence=0.8, signals=["+implement"]
    )
    result = _apply_prompt_append("implement a parser", intent, binding=None)
    assert result.endswith(f"[Guidance: {_DEFAULT_CATEGORY_PROMPTS['code-gen']}]")
    assert result.startswith("implement a parser")


def test_default_prompt_applied_review():
    """Default prompt is appended for review intent."""
    intent = IntentResult(
        primary=IntentCategory.REVIEW, confidence=0.6, signals=["+review"]
    )
    result = _apply_prompt_append("review this PR", intent, binding=None)
    assert "[Guidance:" in result
    assert _DEFAULT_CATEGORY_PROMPTS["review"] in result


def test_default_prompt_applied_each_category():
    """Default prompt snippet is appended for every category."""
    for cat in IntentCategory:
        intent = IntentResult(primary=cat, confidence=0.7, signals=[])
        result = _apply_prompt_append("do something", intent, binding=None)
        expected = _DEFAULT_CATEGORY_PROMPTS[cat.value]
        assert f"[Guidance: {expected}]" in result


# ── Custom binding prompt_template takes precedence ──


def test_binding_template_takes_precedence():
    """When binding has prompt_template, default prompt is NOT appended."""
    intent = IntentResult(
        primary=IntentCategory.CODE_GEN, confidence=0.9, signals=["+implement"]
    )
    binding = CategoryBinding(prompt_template="You are a senior engineer.")
    result = _apply_prompt_append("implement a parser", intent, binding=binding)

    # Binding prepend should be present
    assert result.startswith("[System: You are a senior engineer.]")
    # Default guidance should NOT be present
    assert "[Guidance:" not in result


def test_empty_binding_template_uses_default():
    """When binding exists but prompt_template is empty, default IS appended."""
    intent = IntentResult(
        primary=IntentCategory.DEBUG, confidence=0.8, signals=["+fix"]
    )
    binding = CategoryBinding(preferred_model="codex", prompt_template="")
    result = _apply_prompt_append("fix this bug", intent, binding=binding)

    assert "[System:" not in result
    assert "[Guidance:" in result
    assert _DEFAULT_CATEGORY_PROMPTS["debug"] in result


# ── auto_prompt_append=False disables the feature ──


def test_auto_prompt_append_disabled():
    """Setting auto_prompt_append=False skips prompt append entirely."""
    intent = IntentResult(
        primary=IntentCategory.REVIEW, confidence=0.9, signals=["+review"]
    )
    result = _apply_prompt_append(
        "review my code", intent, binding=None, auto_prompt_append=False
    )
    assert "[Guidance:" not in result
    assert result == "review my code"


def test_auto_prompt_append_disabled_with_binding():
    """auto_prompt_append=False does not affect MER-89 binding prepend."""
    intent = IntentResult(
        primary=IntentCategory.CODE_GEN, confidence=0.9, signals=["+implement"]
    )
    binding = CategoryBinding(prompt_template="Be concise.")
    result = _apply_prompt_append(
        "implement X", intent, binding=binding, auto_prompt_append=False
    )
    # MER-89 prepend still works
    assert result.startswith("[System: Be concise.]")
    # MER-93 guidance not appended (even though binding template blocks it anyway)
    assert "[Guidance:" not in result


# ── Low confidence (<0.3) skips prompt append ──


def test_low_confidence_skips_append():
    """When confidence < 0.3, prompt is NOT appended."""
    intent = IntentResult(
        primary=IntentCategory.CODE_GEN, confidence=0.2, signals=[]
    )
    result = _apply_prompt_append("something vague", intent, binding=None)
    assert "[Guidance:" not in result
    assert result == "something vague"


def test_confidence_exactly_030_appends():
    """Confidence == 0.3 should still trigger append (>= threshold)."""
    intent = IntentResult(
        primary=IntentCategory.DOCS, confidence=0.3, signals=["+document"]
    )
    result = _apply_prompt_append("document the API", intent, binding=None)
    assert "[Guidance:" in result
    assert _DEFAULT_CATEGORY_PROMPTS["docs"] in result


def test_zero_confidence_skips_append():
    """Zero confidence (no keyword matches) skips append."""
    intent = IntentResult(
        primary=IntentCategory.CODE_GEN, confidence=0.0, signals=[]
    )
    result = _apply_prompt_append("???", intent, binding=None)
    assert "[Guidance:" not in result


# ── Prompt is appended (not prepended) to task ──


def test_guidance_appended_not_prepended():
    """[Guidance: ...] appears at the END of the task, not the beginning."""
    intent = IntentResult(
        primary=IntentCategory.REFACTOR, confidence=0.8, signals=["+refactor"]
    )
    result = _apply_prompt_append("refactor the module", intent, binding=None)

    # Task text comes first
    assert result.startswith("refactor the module")
    # Guidance comes last
    lines = result.split("\n")
    last_line = lines[-1]
    assert last_line.startswith("[Guidance:")
    assert last_line.endswith("]")


def test_guidance_separated_by_blank_line():
    """Guidance is separated from the task by a blank line."""
    intent = IntentResult(
        primary=IntentCategory.TEST, confidence=0.7, signals=["+test"]
    )
    result = _apply_prompt_append("write unit tests", intent, binding=None)
    assert "\n\n[Guidance:" in result


# ── Config integration ──


def test_profile_auto_prompt_append_default_true():
    """Profile.auto_prompt_append defaults to True."""
    profile = Profile()
    assert profile.auto_prompt_append is True


def test_profile_auto_prompt_append_false():
    """Profile.auto_prompt_append can be set to False."""
    profile = Profile(auto_prompt_append=False)
    assert profile.auto_prompt_append is False


# ── Integration with classify_intent ──


def test_real_intent_classification_appends_prompt():
    """End-to-end: classify_intent → prompt append for a real task."""
    task = "implement a REST API endpoint for user authentication"
    intent = classify_intent(task)
    # Should classify as code-gen with decent confidence
    assert intent.primary == IntentCategory.CODE_GEN
    assert intent.confidence >= 0.3

    result = _apply_prompt_append(task, intent, binding=None)
    assert "[Guidance:" in result
    assert _DEFAULT_CATEGORY_PROMPTS["code-gen"] in result


def test_real_intent_debug_appends_prompt():
    """End-to-end: debug task gets debug guidance."""
    task = "fix the crash in the parser when input is empty"
    intent = classify_intent(task)
    assert intent.primary == IntentCategory.DEBUG
    assert intent.confidence >= 0.3

    result = _apply_prompt_append(task, intent, binding=None)
    assert _DEFAULT_CATEGORY_PROMPTS["debug"] in result
