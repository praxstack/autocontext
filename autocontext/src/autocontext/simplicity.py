from __future__ import annotations

from typing import Literal, cast

SimplicityMode = Literal["off", "guide", "enforce"]
SIMPLICITY_MODES = frozenset({"off", "guide", "enforce"})
SIMPLICITY_GUIDANCE_MARKER = "[Autocontext simplicity mode]"
SIMPLICITY_GUIDANCE = (
    f"{SIMPLICITY_GUIDANCE_MARKER}\n"
    "Prefer the shortest correct answer. Skip unrequested scaffolding, boilerplate, "
    "future-proofing, and abstractions. Use standard/native capabilities first. "
    "Keep only checks and error handling needed for correctness, safety, or data loss prevention."
)


def normalize_simplicity_mode(value: object | None) -> SimplicityMode:
    mode = "off" if value is None else str(value)
    mode = mode.strip().lower()
    if mode not in SIMPLICITY_MODES:
        raise ValueError("simplicity-mode must be one of: off, guide, enforce")
    return cast(SimplicityMode, mode)


def effective_simplicity_mode(mode: object | None) -> SimplicityMode:
    return "off" if normalize_simplicity_mode(mode) == "off" else "guide"


def append_simplicity_guidance(text: str, mode: object | None) -> str:
    if effective_simplicity_mode(mode) == "off" or SIMPLICITY_GUIDANCE_MARKER in text:
        return text
    return f"{text.rstrip()}\n\n{SIMPLICITY_GUIDANCE}"


def simplicity_mode_metadata(mode: object | None) -> dict[str, str]:
    normalized = normalize_simplicity_mode(mode)
    effective = effective_simplicity_mode(normalized)
    return {
        "simplicity_mode": normalized,
        "simplicity_effective_mode": effective,
        "simplicity_enforcement": "guide-only" if normalized == "enforce" else effective,
    }


def simplicity_mode_warning(mode: object | None) -> str:
    if normalize_simplicity_mode(mode) != "enforce":
        return ""
    return "simplicity_mode=enforce is experimental and guide-only; no hard gates are applied."
