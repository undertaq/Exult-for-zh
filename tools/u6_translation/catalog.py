from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


_TOKENS = re.compile(
    r"@[A-Za-z0-9_]+@|~|\*|<(?:PLAYER_NAME|HONORIFIC|PRONOUN|GENDER_FLAG|VAR)>"
)


def normalize_source(source: str) -> str:
    """Apply the same newline normalization used by the C++ catalog side."""

    return source.replace("\r\n", "\n").replace("\r", "\n")


def source_sha256(source: str) -> str:
    return hashlib.sha256(normalize_source(source).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CatalogEntry:
    kind: str
    key: str
    source: str
    source_sha256: str
    context: str
    origin: str
    protected_tokens: tuple[str, ...]

    @classmethod
    def from_source(
        cls, kind: str, key: str, source: str, context: str, origin: str
    ) -> "CatalogEntry":
        source = normalize_source(source)
        return cls(
            kind,
            key,
            source,
            source_sha256(source),
            context,
            origin,
            tuple(_TOKENS.findall(source)),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "context": self.context,
            "key": self.key,
            "kind": self.kind,
            "origin": self.origin,
            "protected_tokens": list(self.protected_tokens),
            "source": self.source,
            "source_sha256": self.source_sha256,
        }


def _merge(entries: object) -> list[CatalogEntry]:
    merged: dict[tuple[str, str], CatalogEntry] = {}
    for entry in entries:  # type: ignore[union-attr]
        identity = (entry.kind, entry.key)
        previous = merged.get(identity)
        if previous is None:
            merged[identity] = entry
            continue
        if previous.source_sha256 != entry.source_sha256:
            raise ValueError("duplicate key with different source hash: " + entry.key)
        origins = tuple(
            sorted(
                set(
                    origin
                    for value in (previous.origin, entry.origin)
                    for origin in value.split(";")
                    if origin
                )
            )
        )
        context = (
            "location"
            if "location" in (previous.context, entry.context)
            else previous.context
        )
        merged[identity] = CatalogEntry(
            kind=previous.kind,
            key=previous.key,
            source=previous.source,
            source_sha256=previous.source_sha256,
            context=context,
            origin=";".join(origins),
            protected_tokens=previous.protected_tokens,
        )
    return [merged[identity] for identity in sorted(merged)]


def load_catalog(path: Path) -> list[CatalogEntry]:
    entries = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        data = json.loads(line)
        source = normalize_source(data["source"])
        entries.append(
            CatalogEntry(
                kind=data["kind"],
                key=data["key"],
                source=source,
                source_sha256=data["source_sha256"],
                context=data["context"],
                origin=data["origin"],
                protected_tokens=tuple(data.get("protected_tokens", ())),
            )
        )
    return _merge(entries)


def write_catalog(path: Path, entries: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(entry.as_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
        for entry in _merge(entries)  # type: ignore[arg-type]
    )
    path.write_text(content, encoding="utf-8")


def parse_runtime_catalog(path: Path) -> list[CatalogEntry]:
    from .runtime_table import decode_tsv_row

    entries = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line or line.startswith("#"):
            continue
        kind, key, digest, source = decode_tsv_row(line)
        source = normalize_source(source)
        entries.append(
            CatalogEntry(
                kind=kind,
                key=key,
                source=source,
                source_sha256=digest,
                context="gameplay",
                origin="runtime-capture",
                protected_tokens=tuple(_TOKENS.findall(source)),
            )
        )
    return entries
