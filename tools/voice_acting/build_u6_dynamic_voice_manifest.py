#!/usr/bin/env python3
"""Build reviewed-safe, provenance-keyed U6 dynamic voice templates."""

import argparse
import json
from pathlib import Path
import re
import struct
import sys


HERE = Path(__file__).resolve().parent
DEFAULT_NPC_CATALOG = HERE.parents[1] / "u6_voice/u6_npc_catalog.tsv"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import disassemble_usecode
from u6_dynamic_voice import (
    canonicalize_dynamic_template,
    dynamic_voice_key,
    load_zh_translation_templates,
    normalize_translation_source,
    translation_source_sha256,
)


def _offset_key(value):
    return "_".join(
        part[2:] if part.startswith("0x") else part
        for part in str(value).split("_")
    )


def dynamic_line_id(line):
    """Return a stable human-edited override coordinate for one visible page."""
    return (f"0x{int(line['func_id']):04x}:"
            f"{_offset_key(line['offset_key'])}:{int(line['segment'])}")


def _role_lookup_key(function_id, offset_key, segment):
    return (int(function_id), _offset_key(offset_key), int(segment))


def load_role_records(path):
    records = {}
    with open(path, encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = _role_lookup_key(
                record["function_id"], record["offset_key"], record["segment"])
            previous = records.get(key)
            if previous and previous != record:
                raise ValueError(
                    f"conflicting role records for function 0x{key[0]:04x}:"
                    f"{key[1]}:{key[2]} at {path}:{line_number}")
            records[key] = record
    return records


def load_overrides(path):
    if path is None:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("override file must be a JSON object keyed by dynamic line id")
    return data


def _clean_role_text(value):
    value = str(value).replace("@", "")
    value = re.sub(r"\*+$", "", value)
    return value.strip()


def split_role_text(text, explicit_role=None):
    """Split marker-delimited text into role spans, retaining source ranges."""
    explicit_role = str(explicit_role or "").strip().lower()
    if explicit_role in {"speaker", "narrator"}:
        clean = _clean_role_text(text)
        return ([{"role": explicit_role, "text": clean,
                  "start_char": 0, "end_char": len(text)}]
                if clean else [])

    if "@" not in text:
        return []

    spans = []

    def append(role, start, end):
        value = _clean_role_text(text[start:end])
        if not value:
            return
        if spans and spans[-1]["role"] == role:
            spans[-1]["text"] += " " + value
            spans[-1]["end_char"] = end
        else:
            spans.append({"role": role, "text": value,
                          "start_char": start, "end_char": end})

    cursor = 0
    markers = list(re.finditer(r"@([^@]*)@", text))
    if markers:
        for marker in markers:
            append("narrator", cursor, marker.start())
            append("speaker", marker.start() + 1, marker.end() - 1)
            cursor = marker.end()
        append("narrator", cursor, len(text))
        return spans

    positions = [match.start() for match in re.finditer("@", text)]
    role = "narrator" if positions[0] == 0 else "speaker"
    cursor = 0
    for position in positions:
        append(role, cursor, position)
        role = "speaker" if role == "narrator" else "narrator"
        cursor = position + 1
    append(role, cursor, len(text))
    return spans


def _effective_role(line, role_record):
    source = line["source_template_en"]
    role = str((role_record or {}).get("role") or "").strip().lower()
    role_source = str((role_record or {}).get("role_source") or "").strip()
    if role in {"speaker", "narrator"}:
        return role, role_source or "role-manifest"
    if role == "mixed":
        if "@" not in source:
            raise ValueError("mixed role record has no source role markers")
        return None, role_source or "source-markers"
    if "@" in source:
        return None, "source-markers"
    raise ValueError("missing explicit speaker/narrator role provenance")


def _merge_slot_overrides(slots, line_override):
    slot_overrides = line_override.get("slots", {})
    for slot in slots:
        replacement = slot_overrides.get(str(slot["ordinal"]),
                                         slot_overrides.get(slot["ordinal"], {}))
        if replacement:
            if not isinstance(replacement, dict):
                raise ValueError(
                    f"slot override {slot['ordinal']} must be a JSON object")
            slot.update(replacement)
    return slots


def _gender_variants(slots):
    if any(slot.get("semantic_type") in {"pronoun", "gender_flag"}
           for slot in slots):
        return ["male", "female"]
    return [None]


def _canonical_template_pairs(source_en, source_zh, slots, gender_variants,
                              whole_span_override):
    result = {}
    for gender in gender_variants:
        key = gender or "default"
        result[key] = canonicalize_dynamic_template(
            source_en, source_zh, slots, player_gender=gender,
            whole_span_override=whole_span_override)
    return result


def _build_role_spans(source_en, canonical_by_gender, explicit_role,
                      line_id):
    source_spans = split_role_text(source_en, explicit_role)
    if not source_spans:
        raise ValueError(f"{line_id}: no usable role spans were identified")

    result = []
    for index, source_span in enumerate(source_spans):
        span = {
            "index": index,
            "role": source_span["role"],
            "start_char": source_span["start_char"],
            "end_char": source_span["end_char"],
            "requires_audio": bool(re.search(r"[\w\u3400-\u9fff]", source_span["text"])),
            "transcripts": {},
        }
        for gender, transcripts in canonical_by_gender.items():
            en_spans = split_role_text(transcripts["en"], explicit_role)
            zh_spans = split_role_text(transcripts["zh"], explicit_role)
            if ([part["role"] for part in en_spans]
                    != [part["role"] for part in source_spans]):
                raise ValueError(
                    f"{line_id}: canonical English role boundaries differ from source")
            if ([part["role"] for part in zh_spans]
                    != [part["role"] for part in source_spans]):
                raise ValueError(
                    f"{line_id}: zh-Hant role markers do not preserve source boundaries")
            span["transcripts"][gender] = {
                "en": en_spans[index]["text"],
                "zh": zh_spans[index]["text"],
            }
        result.append(span)
    return result


def build_dynamic_voice_manifest(functions_data, translation_templates,
                                 role_records=None, overrides=None,
                                 callers_of=None):
    """Build strict dynamic-only JSONL records from disassembled U6 functions."""
    role_records = role_records or {}
    overrides = overrides or {}
    if isinstance(role_records, list):
        role_records = {
            _role_lookup_key(row["function_id"], row["offset_key"], row["segment"]): row
            for row in role_records
        }

    records = []
    for func in functions_data:
        npc = disassemble_usecode.get_npc_name(func["id"])
        caller_guess = ""
        if callers_of and not npc:
            caller_guess = disassemble_usecode.infer_speaker_from_callers(
                func["id"], callers_of)

        for line in disassemble_usecode.extract_say_lines(func):
            if not line["has_var"] or line["is_book"]:
                continue
            line_id = dynamic_line_id(line)
            override = overrides.get(line_id, {})
            if not isinstance(override, dict):
                raise ValueError(f"{line_id}: override must be a JSON object")
            slots = []
            for part in line["source_parts"]:
                if part["kind"] != "dynamic":
                    continue
                slot = {
                    "ordinal": part["ordinal"],
                    "label": part["label"],
                    "semantic_type": part.get("semantic_type", "unknown"),
                    "source_func_id": part["source_func_id"],
                    "source_offset": part["source_offset"],
                    "variable_index": part["variable_index"],
                }
                if part.get("pronoun_form"):
                    slot["pronoun_form"] = part["pronoun_form"]
                slots.append(slot)
            slots = _merge_slot_overrides(slots, override)
            whole_span_override = override.get("whole_span")
            source_zh = (override.get("source_template_zh")
                         or disassemble_usecode_translation_lookup(
                             line["source_template_en"], translation_templates))
            if source_zh is None:
                if whole_span_override and isinstance(whole_span_override, dict):
                    source_zh = whole_span_override.get("zh")
                if source_zh is None:
                    raise ValueError(f"{line_id}: missing zh-Hant translation template")

            role_record = role_records.get(_role_lookup_key(
                line["func_id"], line["offset_key"], line["segment"]))
            explicit_role, role_source = _effective_role(line, role_record)
            gender_variants = _gender_variants(slots)
            try:
                canonical = _canonical_template_pairs(
                    line["source_template_en"], source_zh, slots,
                    gender_variants, whole_span_override)
                role_spans = _build_role_spans(
                    line["source_template_en"], canonical,
                    explicit_role, line_id)
            except ValueError as exc:
                raise ValueError(f"{line_id}: {exc}") from exc

            identity = {
                "function_id": line["func_id"],
                "segment": line["segment"],
                "source_template_en": normalize_translation_source(
                    line["source_template_en"]),
                "source_parts": _apply_classified_slots_to_parts(
                    line["source_parts"], slots),
                "role_spans": [
                    {key: span[key] for key in
                     ("role", "start_char", "end_char")}
                    for span in role_spans
                ],
            }
            records.append({
                "schema": "u6-dynamic-voice-template-v1",
                "line_id": line_id,
                "key": dynamic_voice_key(identity),
                "function_id": line["func_id"],
                "npc": npc,
                "speaker": line["speaker"],
                "speaker_func_id": line["speaker_func_id"],
                "caller_guess": caller_guess,
                "offset_key": line["offset_key"],
                "addsi_offsets": line["addsi_offsets"],
                "code_addr": line["code_addr"],
                "segment": line["segment"],
                "total_segments": line["total_segments"],
                "dynamic": True,
                "source_template_en": normalize_translation_source(
                    line["source_template_en"]),
                "source_template_zh": source_zh,
                "translation_source_sha256": translation_source_sha256(
                    line["source_template_en"]),
                "source_parts": line["source_parts"],
                "slots": slots,
                "player_gender_variants": gender_variants,
                "canonical_transcripts": canonical,
                "role_source": role_source,
                "role_spans": role_spans,
                "whole_span_override": whole_span_override,
            })

    validate_dynamic_voice_manifest(records)
    return sorted(records, key=lambda item: (
        item["function_id"], item["offset_key"], item["segment"]))


def disassemble_usecode_translation_lookup(source_en, templates):
    return templates.get(translation_source_sha256(source_en))


def _apply_classified_slots_to_parts(source_parts, slots):
    by_ordinal = {int(slot["ordinal"]): slot for slot in slots}
    result = []
    for part in source_parts:
        value = dict(part)
        if value.get("kind") == "dynamic":
            slot = by_ordinal[int(value["ordinal"])]
            value["semantic_type"] = slot["semantic_type"]
            if slot.get("pronoun_form"):
                value["pronoun_form"] = slot["pronoun_form"]
        result.append(value)
    return result


def validate_dynamic_voice_manifest(records):
    """Reject incomplete transcripts, role coverage, and key collisions."""
    keys = {}
    unresolved = re.compile(r"<VAR[^>]*>|<(?:PLAYER_NAME|HONORIFIC|PRONOUN|GENDER_FLAG)>")
    for row_index, row in enumerate(records):
        line_id = row.get("line_id", f"row {row_index}")
        key = row.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"dyn_[0-9a-f]{64}", key):
            raise ValueError(f"{line_id}: invalid dynamic voice key")
        serialized = json.dumps(row, ensure_ascii=False, sort_keys=True)
        previous = keys.get(key)
        if previous is not None and previous != serialized:
            raise ValueError(f"conflicting duplicate key {key}")
        keys[key] = serialized
        if not row.get("source_template_zh"):
            raise ValueError(f"{line_id}: missing zh-Hant source template")
        if not row.get("slots"):
            raise ValueError(f"{line_id}: dynamic template has no classified slots")
        for slot in row["slots"]:
            if slot.get("semantic_type") == "unknown" and not row.get("whole_span_override"):
                raise ValueError(
                    f"{line_id}: unknown dynamic slot VAR{slot.get('ordinal')} needs a reviewed override")
        if not row.get("role_spans"):
            raise ValueError(f"{line_id}: missing role spans")
        expected_genders = row.get("player_gender_variants")
        canonical = row.get("canonical_transcripts") or {}
        if set(canonical) != {gender or "default" for gender in expected_genders}:
            raise ValueError(f"{line_id}: missing full-line gender transcript variant")
        for gender, pair in canonical.items():
            for language in ("en", "zh"):
                text = pair.get(language)
                if not isinstance(text, str) or not text.strip():
                    raise ValueError(
                        f"{line_id}: missing full-line {language} transcript for {gender}")
                if unresolved.search(text):
                    raise ValueError(
                        f"{line_id}: unresolved placeholder in full-line {language}/{gender} transcript")
        for span in row["role_spans"]:
            transcripts = span.get("transcripts") or {}
            if set(transcripts) != {gender or "default" for gender in expected_genders}:
                raise ValueError(f"{line_id}: missing player-gender transcript variant")
            for gender, pair in transcripts.items():
                for language in ("en", "zh"):
                    text = pair.get(language)
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError(
                            f"{line_id}: missing {language} transcript for {gender}")
                    if unresolved.search(text):
                        raise ValueError(
                            f"{line_id}: unresolved placeholder in {language}/{gender} transcript")
    return True


def _read_functions(usecode_path, npc_catalog=None):
    if npc_catalog:
        disassemble_usecode.load_npc_catalog(npc_catalog)
    data = Path(usecode_path).read_bytes()
    offset = disassemble_usecode.skip_symbol_table(data, 0)
    functions = {}
    while offset < len(data):
        try:
            function_id, function_data, extended, next_offset = (
                disassemble_usecode.parse_function(data, offset))
            if next_offset <= offset or next_offset > len(data):
                raise ValueError(
                    f"function 0x{function_id:04x} extends past end of file")
            functions[function_id] = (function_data, extended)
            offset = next_offset
        except (OSError, ValueError, IndexError, struct.error) as exc:
            if offset != len(data):
                raise ValueError(
                    f"failed parsing usecode at byte 0x{offset:x}: {exc}") from exc
            break
    result = []
    for function_id, (function_data, extended) in sorted(functions.items()):
        result.append(disassemble_usecode.disassemble_function(
            function_id, function_data, extended))
    return result


def _jsonl(records):
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                   for row in records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usecode-file", required=True)
    parser.add_argument("--translation-tsv", required=True)
    parser.add_argument("--overrides")
    parser.add_argument("--roles-manifest")
    parser.add_argument("--npc-catalog", default=str(DEFAULT_NPC_CATALOG))
    parser.add_argument("--output", required=True)
    parser.add_argument("--check", action="store_true",
                        help="validate and compare with the existing output; never write")
    args = parser.parse_args(argv)

    functions = _read_functions(args.usecode_file, args.npc_catalog)
    translations = load_zh_translation_templates(args.translation_tsv)
    roles = load_role_records(args.roles_manifest) if args.roles_manifest else {}
    overrides = load_overrides(args.overrides)
    callers = disassemble_usecode.build_caller_map({
        func["id"]: func for func in functions
    })
    records = build_dynamic_voice_manifest(
        functions, translations, roles, overrides, callers_of=callers)
    output = Path(args.output)
    content = _jsonl(records)
    if args.check:
        if not output.is_file():
            raise ValueError(f"--check output does not exist: {output}")
        existing = output.read_text(encoding="utf-8")
        if existing != content:
            raise ValueError(f"manifest is stale: {output}")
        print(f"Validated {len(records)} dynamic voice templates: {output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(f"Wrote {len(records)} dynamic voice templates: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2)
