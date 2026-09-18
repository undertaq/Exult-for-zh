from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .runtime_table import decode_tsv_row


class CapturedSpeaker(str):
    """A display-compatible speaker name retaining its runtime capture ID."""

    def __new__(cls, speaker: str, speaker_id: int) -> "CapturedSpeaker":
        value = super().__new__(cls, speaker)
        value.speaker_id = speaker_id
        return value


@dataclass(frozen=True)
class SpeakerCaptureRow:
    kind: str
    key: str
    speaker_id: int
    speaker: str


def load_speaker_capture(path: Path) -> list[SpeakerCaptureRow]:
    rows: list[SpeakerCaptureRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        kind, key, raw_id, speaker = decode_tsv_row(line)
        try:
            speaker_id = int(raw_id, 10)
        except ValueError as error:
            raise ValueError(f"invalid speaker_id: {raw_id!r}") from error
        rows.append(SpeakerCaptureRow(kind, key, speaker_id, speaker))
    return rows


def speaker_map_from_capture(rows: list[SpeakerCaptureRow]) -> dict[str, str]:
    observations: dict[str, set[tuple[int, str]]] = {}
    for row in rows:
        if row.kind != "dialogue":
            continue
        observations.setdefault(row.key, set()).add((row.speaker_id, row.speaker.strip()))

    mapping: dict[str, str] = {}
    for key, values in observations.items():
        names = sorted({name for _, name in values if name})
        if len(names) == 1:
            ids = sorted({speaker_id for speaker_id, _ in values})
            if len(ids) == 1:
                mapping[key] = CapturedSpeaker(names[0], ids[0])
            else:
                mapping[key] = "Ambiguous · " + " / ".join(
                    f"NPC {speaker_id}" for speaker_id in ids
                )
            continue
        elif names:
            mapping[key] = "Ambiguous · " + " / ".join(names)
            continue
        ids = sorted({speaker_id for speaker_id, _ in values})
        if len(ids) == 1:
            mapping[key] = f"Unresolved · NPC {ids[0]}"
        else:
            mapping[key] = "Ambiguous · " + " / ".join(
                f"NPC {speaker_id}" for speaker_id in ids
            )
    return mapping
