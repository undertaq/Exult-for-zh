"""Load the shared English-only U6 entity and professional-term inventory.

The manifest is deliberately small and data-driven.  It can include the
legacy two-column name list, while new categories and policies live in one
canonical file.  All consumers (audit, extraction, and prompts) use this
loader so adding a new protected term does not require a code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_CANONICAL_HEADER = ("category", "en", "policy")
_LEGACY_NAME_HEADER = ("category", "en")
_CATEGORY_MAP = {
    "npc": "person",
    "person": "person",
    "place": "location",
    "town": "location",
    "location": "location",
    "proper": "proper",
}
_CANONICAL_CATEGORIES = frozenset({"person", "location", "professional", "proper"})
_INCLUDE_RE = re.compile(r"^#\s*include\s+(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class EnglishTerm:
    """One English-only inventory entry."""

    category: str
    en: str
    policy: str


def policy_tokens(policy: str) -> frozenset[str]:
    """Return normalized policy flags from a ``+``/``|`` separated value."""

    return frozenset(
        token
        for token in re.split(r"[+,|/;:\s]+", policy.lower())
        if token
    )


def _canonicalize_legacy_category(category: str) -> str:
    try:
        return _CATEGORY_MAP[category.lower()]
    except KeyError as error:
        raise ValueError(f"invalid U6 English-term category: {category!r}") from error


def _insert(
    terms: dict[tuple[str, str], EnglishTerm], term: EnglishTerm, source: Path
) -> None:
    key = (term.category, term.en.casefold())
    previous = terms.get(key)
    if previous is not None:
        if previous.policy != term.policy:
            raise ValueError(
                f"conflicting U6 English-term policy for {term.category}/{term.en!r} "
                f"({source})"
            )
        return
    terms[key] = term


def _load_file(
    path: Path,
    terms: dict[tuple[str, str], EnglishTerm],
    stack: tuple[Path, ...],
) -> None:
    resolved = path.resolve()
    if resolved in stack:
        chain = " -> ".join(str(item) for item in (*stack, resolved))
        raise ValueError(f"cyclic U6 English-term include: {chain}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"cannot read U6 English-term file {path}: {error}") from error

    header: tuple[str, ...] | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        include_match = _INCLUDE_RE.fullmatch(stripped)
        if include_match:
            include_path = (path.parent / include_match.group(1)).resolve()
            _load_file(include_path, terms, (*stack, resolved))
            continue
        if stripped.startswith("#"):
            continue
        fields = tuple(line.split("\t"))
        if header is None:
            header = fields
            if header not in {_CANONICAL_HEADER, _LEGACY_NAME_HEADER}:
                raise ValueError(
                    f"invalid U6 English-term header in {path}: {line!r}"
                )
            continue
        if not all(fields):
            raise ValueError(f"invalid U6 English-term row in {path}: {line!r}")
        if header == _LEGACY_NAME_HEADER:
            if len(fields) != 2:
                raise ValueError(f"invalid legacy U6 name row in {path}: {line!r}")
            category, english = fields
            category = _canonicalize_legacy_category(category)
            _insert(terms, EnglishTerm(category, english, "protected"), path)
            continue
        if len(fields) != 3:
            raise ValueError(f"invalid U6 English-term row in {path}: {line!r}")
        category, english, policy = fields
        category = category.lower()
        if category not in _CANONICAL_CATEGORIES:
            raise ValueError(f"invalid U6 English-term category: {category!r}")
        _insert(terms, EnglishTerm(category, english, policy), path)

    if header is None:
        raise ValueError(f"missing U6 English-term header in {path}")


def load_english_terms(path: Path) -> tuple[EnglishTerm, ...]:
    """Load a canonical manifest and all relative ``# include`` files."""

    terms: dict[tuple[str, str], EnglishTerm] = {}
    _load_file(path, terms, ())
    return tuple(terms.values())
