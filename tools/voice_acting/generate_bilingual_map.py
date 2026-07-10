#!/usr/bin/env python3
"""Generate the runtime bilingual voice map from the reviewed mapping JSON."""

import argparse
import json
import struct
from pathlib import Path


DEFAULT_INPUT = Path("tools/voice_acting/bilingual_mapping_review.json")
DEFAULT_OUTPUT = Path("voice/bilingual_map.dat")


def has_text(value):
    return bool(str(value or "").strip())


def has_runtime_identity(row, lang):
    return (
        has_text(row.get(f"{lang}_func_id"))
        and has_text(row.get(f"{lang}_offset_key"))
        and row.get(f"{lang}_segment") is not None
        and str(row.get(f"{lang}_segment")).strip() != ""
    )


def normalize_func_id(value, field_name):
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError(f"missing {field_name}")
    if text.startswith("0x"):
        text = text[2:]
    return int(text, 16)


def normalize_offset_key(value, field_name):
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError(f"missing {field_name}")
    parts = []
    for part in text.split("_"):
        part = part.strip()
        if part.startswith("0x"):
            part = part[2:]
        if not part:
            raise ValueError(f"invalid {field_name}: {value!r}")
        parts.append(part)
    return "_".join(parts)


def normalize_segment(value, field_name):
    text = str(value).strip() if value is not None else ""
    if text == "":
        raise ValueError(f"missing {field_name}")
    segment = int(text, 0)
    if not 0 <= segment <= 0xFFFF:
        raise ValueError(f"{field_name} out of BLMP range: {segment}")
    return segment


def load_canonical_mappings(review_path):
    rows = json.loads(Path(review_path).read_text(encoding="utf-8"))
    mappings = []
    seen_zh = {}
    seen_en = {}

    for index, row in enumerate(rows, start=1):
        if not (has_text(row.get("en_text")) and has_text(row.get("zh_text"))):
            continue
        if not (has_runtime_identity(row, "en") and has_runtime_identity(row, "zh")):
            continue

        en_func_id = normalize_func_id(row.get("en_func_id"), f"row {index} en_func_id")
        zh_func_id = normalize_func_id(row.get("zh_func_id"), f"row {index} zh_func_id")
        en_offset_key = normalize_offset_key(
            row.get("en_offset_key"), f"row {index} en_offset_key"
        )
        zh_offset_key = normalize_offset_key(
            row.get("zh_offset_key"), f"row {index} zh_offset_key"
        )
        en_segment = normalize_segment(row.get("en_segment"), f"row {index} en_segment")
        zh_segment = normalize_segment(row.get("zh_segment"), f"row {index} zh_segment")
        if en_segment != zh_segment:
            raise ValueError(
                f"row {index} has different EN/ZH segments: "
                f"en={en_segment}, zh={zh_segment}"
            )

        mapping = (zh_func_id, zh_offset_key, zh_segment, en_func_id, en_offset_key)
        zh_key = mapping[:3]
        en_key = (en_func_id, en_offset_key, en_segment)
        if zh_key in seen_zh and seen_zh[zh_key] != mapping:
            raise ValueError(f"row {index} conflicts with prior ZH runtime key {zh_key}")
        if en_key in seen_en and seen_en[en_key] != mapping:
            raise ValueError(f"row {index} conflicts with prior EN runtime key {en_key}")
        if zh_key in seen_zh or en_key in seen_en:
            continue
        seen_zh[zh_key] = mapping
        seen_en[en_key] = mapping
        mappings.append(mapping)

    return mappings


def write_blmp(mappings, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        f.write(b"BLMP")
        f.write(struct.pack("<I", len(mappings)))
        for zh_func_id, zh_offset_key, segment, en_func_id, en_offset_key in mappings:
            f.write(struct.pack("<i", zh_func_id))
            f.write(zh_offset_key.encode("utf-8") + b"\0")
            f.write(struct.pack("<H", segment))
            f.write(struct.pack("<i", en_func_id))
            f.write(en_offset_key.encode("utf-8") + b"\0")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate voice/bilingual_map.dat from bilingual_mapping_review.json"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    mappings = load_canonical_mappings(args.input)
    write_blmp(mappings, args.output)
    print(f"Wrote {len(mappings)} mappings to {args.output}")


if __name__ == "__main__":
    main()
