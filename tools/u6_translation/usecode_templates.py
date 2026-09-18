"""Discover positional dialogue templates from compiled U6 usecode.

The game can build a sentence by pushing literal fragments with ``PUSHS``,
joining them with ``ADD``, storing the result in a local, and appending that
local with ``ADDSV``.  UCXT exposes the literal fragments as separate rows, so
the complete template would otherwise be invisible to the static catalog.

This module mirrors the small expression subset used by the runtime
translation trace.  It deliberately does not contain NPC names or sentence
registries: every eligible expression is converted to positional ``<VARn>``
slots and a source-stable hash key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Any

from .catalog import CatalogEntry, source_sha256


@dataclass(frozen=True)
class _ExpressionPart:
    kind: str
    value: str | int


@dataclass(frozen=True)
class _Expression:
    kind: str
    left: "_Expression | None" = None
    right: "_Expression | None" = None
    value: str | int = ""


def _static(value: str) -> _Expression:
    return _Expression("static", value=value)


def _dynamic(local: int) -> _Expression:
    return _Expression("dynamic", value=local)


def _concat(left: _Expression | None, right: _Expression | None) -> _Expression | None:
    if left is None or right is None:
        return None
    return _Expression("concat", left=left, right=right)


def _flatten(expression: _Expression | None) -> list[_ExpressionPart]:
    if expression is None:
        return []
    if expression.kind == "static":
        return [_ExpressionPart("static", expression.value)]
    if expression.kind == "dynamic":
        return [_ExpressionPart("dynamic", expression.value)]
    if expression.kind == "concat":
        return _flatten(expression.left) + _flatten(expression.right)
    return []


def _template(parts: list[_ExpressionPart]) -> str | None:
    # Without a literal between two dynamic values, the runtime cannot prove
    # where one value ends and the next begins. The C++ matcher deliberately
    # rejects that ambiguous shape, so do not emit a catalog row that could
    # never be selected safely.
    if any(
        left.kind == "dynamic" and right.kind == "dynamic"
        for left, right in zip(parts, parts[1:])
    ):
        return None
    result: list[str] = []
    variable_index = 0
    for part in parts:
        if part.kind == "dynamic":
            result.append(f"<VAR{variable_index}>")
            variable_index += 1
        else:
            result.append(str(part.value))
    return "".join(result)


def _is_stack_barrier(name: str) -> bool:
    """Return whether an instruction invalidates our partial operand stack."""

    # String-expression instructions are handled explicitly by the caller.
    # Every other operation may consume or reorder operands in ways that are
    # outside this small data-flow model.  Clearing the partial stack keeps
    # the extractor fail-closed instead of inventing a template.
    return name not in {"pushs", "push", "add", "pop", "addsi", "addsv", "say"}


def _templates_from_function(function: dict[str, Any]) -> set[str]:
    """Infer templates from one disassembled function's linear expressions."""

    stack: list[_Expression | None] = []
    locals_: dict[int, _Expression] = {}
    string_parts: list[_ExpressionPart] = []
    has_assembled_expression = False
    templates: set[str] = set()

    for _address, _raw, name, params, _comment in function["instructions"]:
        if name == "pushs" and params:
            if any(value is None for value in stack):
                stack.clear()
            stack.append(_static(function["strings"].get(params[0], "")))
            continue

        if name == "push" and params:
            if any(value is None for value in stack):
                stack.clear()
            stack.append(locals_.get(params[0], _dynamic(params[0])))
            continue

        if name == "add":
            if len(stack) < 2:
                stack.clear()
                continue
            right = stack.pop()
            left = stack.pop()
            stack.append(_concat(left, right))
            continue

        if name == "pop" and params:
            if stack and stack[-1] is not None:
                locals_[params[0]] = stack.pop()  # type: ignore[assignment]
            else:
                locals_.pop(params[0], None)
                stack.clear()
            continue

        if name == "addsi" and params:
            string_parts.append(
                _ExpressionPart("static", function["strings"].get(params[0], ""))
            )
            static_count = sum(
                part.kind == "static" and bool(str(part.value))
                for part in string_parts
            )
            dynamic_count = sum(part.kind == "dynamic" for part in string_parts)
            if static_count >= 1 and dynamic_count >= 1:
                has_assembled_expression = True
            stack.clear()
            continue

        if name == "addsv" and params:
            expression = locals_.get(params[0])
            parts = _flatten(expression)
            if not parts:
                # ADDSV is a dynamic provenance boundary even when the
                # compiler filled the local from a literal branch (for
                # example, ``we`` versus ``I``).  The runtime therefore
                # exposes that value as a slot; retain the boundary instead
                # of treating it as a static source string.
                parts = [_ExpressionPart("dynamic", params[0])]
            elif all(part.kind == "static" for part in parts):
                # A literal assigned to a local and later passed through
                # ADDSV has the same runtime shape as any other dynamic
                # value.  Do not bake the current branch value into the
                # catalog template.
                parts = [_ExpressionPart("dynamic", params[0])]

            string_parts.extend(parts)
            static_count = sum(
                part.kind == "static" and bool(str(part.value))
                for part in string_parts
            )
            dynamic_count = sum(part.kind == "dynamic" for part in string_parts)
            # Any literal anchor makes a positional template safe.  This
            # includes a direct ADDSI/ADDSV sequence and assembled locals;
            # adjacent dynamic slots are still rejected by ``_template``.
            if static_count >= 1 and dynamic_count >= 1:
                has_assembled_expression = True
            stack.clear()
            continue

        if name == "say":
            if has_assembled_expression:
                dynamic_count = sum(part.kind == "dynamic" for part in string_parts)
                if dynamic_count:
                    source_template = _template(string_parts)
                    if source_template is not None and "<VAR" in source_template:
                        templates.add(source_template)
            string_parts.clear()
            has_assembled_expression = False
            stack.clear()
            continue

        if _is_stack_barrier(name):
            stack.clear()
            # Do not let an unrelated opcode join fragments from two
            # different display expressions. The extractor is intentionally
            # conservative: only one contiguous, statically recoverable
            # expression may produce a catalog template.
            string_parts.clear()
            has_assembled_expression = False

    return templates


def extract_compiled_dialogue_templates(usecode: Path) -> list[CatalogEntry]:
    """Return source-stable catalog entries for assembled dialogue templates."""

    # Import lazily so the ordinary catalog/audit helpers remain usable even
    # when the optional voice-acting tooling is not installed.  The module is
    # importable as a namespace package after its direct-script import fallback
    # is applied in ``disassemble_usecode.py``.
    from tools.voice_acting import disassemble_usecode as disassembler

    data = usecode.resolve().read_bytes()
    try:
        offset = disassembler.skip_symbol_table(data, 0)
    except (IndexError, ValueError, TypeError, struct.error):
        return []
    entries: dict[tuple[int, str], CatalogEntry] = {}
    while offset < len(data):
        try:
            function_id, function_data, extended, next_offset = (
                disassembler.parse_function(data, offset)
            )
        except (IndexError, ValueError, TypeError, struct.error):
            break
        # A fixture or partially written file may contain a plausible header
        # whose declared function length runs past EOF.  Treat that as an
        # unparseable tail instead of passing it to the disassembler and
        # turning a catalog extraction into a hard failure.
        if next_offset <= offset or next_offset > len(data):
            break
        try:
            function = disassembler.disassemble_function(
                function_id, function_data, extended
            )
        except (IndexError, ValueError, TypeError, struct.error):
            break
        for source_template in _templates_from_function(function):
            digest = source_sha256(source_template)
            key = f"dialogue:0x{function_id:04x}:fallback_{digest[:16]}:0"
            entries[(function_id, source_template)] = CatalogEntry.from_source(
                "dialogue",
                key,
                source_template,
                "gameplay",
                "static-usecode-template",
            )
        if next_offset <= offset:
            break
        offset = next_offset
    return sorted(entries.values(), key=lambda entry: entry.key)
