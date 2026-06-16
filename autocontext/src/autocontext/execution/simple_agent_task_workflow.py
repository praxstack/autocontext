"""Prompt helpers for simple queued agent tasks."""

from __future__ import annotations

from autocontext.providers.base import LLMProvider
from autocontext.scenarios.agent_task import AgentTaskResult
from autocontext.simplicity import append_simplicity_guidance


def generate_simple_agent_task_output(
    *,
    provider: LLMProvider,
    model: str,
    task_prompt: str,
    reference_context: str | None = None,
    required_concepts: list[str] | None = None,
    simplicity_mode: str = "off",
) -> str:
    """Generate initial output for a simple queued task."""
    result = provider.complete(
        system_prompt="You are a skilled writer and analyst. Complete the task precisely.",
        user_prompt=build_simple_agent_task_user_prompt(
            task_prompt=task_prompt,
            reference_context=reference_context,
            required_concepts=required_concepts,
            simplicity_mode=simplicity_mode,
        ),
        model=model,
    )
    return result.text


def revise_simple_agent_task_output(
    *,
    provider: LLMProvider,
    model: str,
    task_prompt: str,
    output: str,
    judge_result: AgentTaskResult,
    revision_prompt: str | None = None,
    reference_context: str | None = None,
    required_concepts: list[str] | None = None,
    objective_feedback: str | None = None,
    simplicity_mode: str = "off",
) -> str:
    """Revise output for a simple queued task."""
    result = provider.complete(
        system_prompt=(
            "You are revising content based on expert feedback. Improve the output. "
            "IMPORTANT: Return ONLY the revised content. Do NOT include analysis, "
            "explanations, headers like '## Revised Output', or self-assessment. "
            "Just output the improved version directly."
        ),
        user_prompt=build_simple_agent_task_revision_prompt(
            task_prompt=task_prompt,
            output=output,
            judge_result=judge_result,
            revision_prompt=revision_prompt,
            reference_context=reference_context,
            required_concepts=required_concepts,
            objective_feedback=objective_feedback,
            simplicity_mode=simplicity_mode,
        ),
        model=model,
    )
    return result.text


def build_simple_agent_task_user_prompt(
    *,
    task_prompt: str,
    reference_context: str | None = None,
    required_concepts: list[str] | None = None,
    simplicity_mode: str = "off",
) -> str:
    """Build the direct-generation prompt for a simple queued task."""
    blocks = [
        append_simplicity_guidance(task_prompt.strip(), simplicity_mode),
        _build_reference_context_block(reference_context),
        _build_required_concepts_block(required_concepts),
    ]
    return "\n\n".join(block for block in blocks if block)


def build_simple_agent_task_revision_prompt(
    *,
    task_prompt: str,
    output: str,
    judge_result: AgentTaskResult,
    revision_prompt: str | None = None,
    reference_context: str | None = None,
    required_concepts: list[str] | None = None,
    objective_feedback: str | None = None,
    simplicity_mode: str = "off",
) -> str:
    """Build the revision prompt for a simple queued task."""
    instruction = revision_prompt or (
        "Revise the following output based on the judge's feedback. "
        "Maintain what works, fix what doesn't."
    )
    blocks = [
        instruction,
        f"## Original Output\n{output}",
        f"## Judge Score: {judge_result.score:.2f}",
        f"## Judge Feedback\n{judge_result.reasoning}",
        _build_objective_feedback_block(objective_feedback),
        _build_reference_context_block(reference_context),
        _build_required_concepts_block(required_concepts),
        f"## Task\n{append_simplicity_guidance(task_prompt, simplicity_mode)}",
        "Produce an improved version:",
    ]
    return "\n\n".join(block for block in blocks if block)


def _build_reference_context_block(reference_context: str | None) -> str:
    trimmed_reference_context = (reference_context or "").strip()
    if not trimmed_reference_context:
        return ""
    return f"## Reference Context\n{trimmed_reference_context}"


def _build_required_concepts_block(required_concepts: list[str] | None) -> str:
    normalized_concepts = [concept.strip() for concept in required_concepts or [] if concept.strip()]
    if not normalized_concepts:
        return ""
    concepts = "\n".join(f"- {concept}" for concept in normalized_concepts)
    return f"## Required Concepts\n{concepts}"


def _build_objective_feedback_block(objective_feedback: str | None) -> str:
    trimmed_objective_feedback = (objective_feedback or "").strip()
    if not trimmed_objective_feedback:
        return ""
    return f"## Objective Verification Feedback\n{trimmed_objective_feedback}"


__all__ = [
    "build_simple_agent_task_revision_prompt",
    "build_simple_agent_task_user_prompt",
    "generate_simple_agent_task_output",
    "revise_simple_agent_task_output",
]
