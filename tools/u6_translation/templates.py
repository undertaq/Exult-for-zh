"""Generic helpers for runtime-assembled dialogue templates.

The runtime records the fragments that were appended to a dialogue string.
This module deliberately contains no NPC names or sentence registry: every
observed sequence is converted to the same positional placeholder protocol.
"""

from __future__ import annotations

from collections.abc import Iterable
import re


def canonical_template_from_parts(parts: Iterable[tuple[str, bool]]) -> str:
    """Build a source template from ``(text, is_dynamic)`` fragments.

    Static fragments remain literal. Dynamic fragments are numbered by their
    appearance order, allowing arbitrary usecode values and placeholder names
    without a hard-coded sentence list.
    """

    result: list[str] = []
    dynamic_index = 0
    for text, is_dynamic in parts:
        if is_dynamic:
            result.append(f"<VAR{dynamic_index}>")
            dynamic_index += 1
        else:
            result.append(text)
    return "".join(result)


def placeholder_names(source: str) -> tuple[str, ...]:
    """Return valid angle-placeholder tokens in source order."""

    return tuple(re.findall(r"<[A-Za-z][A-Za-z0-9_]*>", source))
