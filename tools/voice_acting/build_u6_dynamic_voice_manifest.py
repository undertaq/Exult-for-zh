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
_SEMANTIC_SLOT_LABELS = {
    "player_name": "<PLAYER_NAME>",
    "honorific": "<HONORIFIC>",
    "number": "<NUMBER>",
    "numeric_value": "<NUMBER>",
    "greeting_time": "<TIME_OF_DAY>",
    "day_period": "<TIME_OF_DAY>",
    "direction": "<DIRECTION>",
    "person_name": "<PERSON_NAME>",
    "npc_name": "<NPC_NAME>",
    "topic_name": "<TOPIC_NAME>",
    "place_name": "<PLACE_NAME>",
    "item_name": "<ITEM_NAME>",
    "pronoun": "<PRONOUN>",
    "gender_flag": "<GENDER_FLAG>",
}
_DEBUG_OUTPUT_FUNCTIONS = {0x03BB}
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import disassemble_usecode
from u6_dynamic_voice import (
    canonicalize_dynamic_template,
    dynamic_voice_key,
    load_zh_translation_templates,
    lookup_zh_translation_template,
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
    function_id = int(line.get("voice_func_id", line["func_id"]))
    key = (f"0x{function_id:04x}:"
           f"{_offset_key(line['offset_key'])}:{int(line['segment'])}")
    dynamic_origins = [
        part for part in line.get("source_parts", [])
        if part.get("kind") == "dynamic"
    ]
    if dynamic_origins:
        suffix = "_".join(
            f"{int(part['source_func_id']):04x}_{int(part['source_offset']):x}_"
            f"{int(part['variable_index'])}"
            for part in dynamic_origins
        )
        key += f":adsv_{suffix}"
    if int(line.get("expression_variant", 0)):
        key += f":v{int(line['expression_variant'])}"
    return key


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


def load_dynamic_voice_exclusions(path):
    """Read exact, source-hash-pinned exclusions for non-conversation output."""
    if path is None:
        return {}
    records = {}
    with open(path, encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid exclusion JSON at {path}:{line_number}") from exc
            line_id = str(record.get("line_id") or "")
            source_hash = str(record.get("source_sha256") or "")
            source_template = str(record.get("source_template_en") or "")
            category = str(record.get("category") or "")
            reason = str(record.get("reason") or "").strip()
            if (record.get("schema") != "u6-dynamic-voice-exclusion-v1"
                    or not line_id
                    or not re.fullmatch(r"[0-9a-f]{64}", source_hash)
                    or not source_template
                    or translation_source_sha256(source_template) != source_hash
                    or category not in {
                        "ui_fragment", "action_narration", "debug_output",
                        "book_text"}
                    or not reason):
                raise ValueError(
                    f"invalid dynamic voice exclusion at {path}:{line_number}")
            if (category == "debug_output"
                    and record.get("function_id") not in _DEBUG_OUTPUT_FUNCTIONS):
                raise ValueError(
                    f"debug-output exclusion must name an audited function at "
                    f"{path}:{line_number}")
            if line_id in records and records[line_id] != record:
                raise ValueError(
                    f"conflicting exclusions for {line_id} at {path}:{line_number}")
            records[line_id] = record
    return records


def _clean_role_text(value):
    value = str(value).replace("@", "")
    value = re.sub(r"\*+$", "", value)
    return value.strip()


def sanitize_dynamic_voice_translation(source_en, source_zh):
    """Drop a Latin-language tail not covered by a terminal source marker."""
    source_end = re.sub(r"[\s*]+$", "", str(source_en))
    if not source_end.endswith("@") or "@" not in source_zh:
        return source_zh
    marker_end = source_zh.rfind("@")
    if marker_end == 0 or source_zh[marker_end - 1] != "@":
        return source_zh
    tail = source_zh[marker_end + 1:]
    tail_without_slots = re.sub(r"<(?:VAR\d+|PLAYER_NAME|HONORIFIC|PRONOUN)>",
                                "", tail)
    if (re.search(r"[A-Za-z]", tail_without_slots)
            and not re.search(r"[A-Za-z]",
                              source_end[source_end.rfind("@") + 1:])):
        return source_zh[:marker_end + 1]
    return source_zh


def normalize_dynamic_slot_placeholders(source_zh, slots):
    """Convert semantic slot labels in translations to canonical VAR ordinals."""
    label_types = {}
    for semantic_type, label in _SEMANTIC_SLOT_LABELS.items():
        label_types.setdefault(label[1:-1], set()).add(semantic_type)

    used_ordinals = {
        int(match.group(1))
        for match in re.finditer(r"<VAR([0-9]+)>", source_zh)
    }
    pattern = re.compile(r"<([A-Z_]+)>")

    def replace(match):
        label = match.group(1)
        accepted_types = label_types.get(label)
        if accepted_types is None:
            return match.group(0)
        candidates = [
            int(slot["ordinal"])
            for slot in slots
            if slot.get("semantic_type") in accepted_types
            and int(slot["ordinal"]) not in used_ordinals
        ]
        if not candidates:
            raise ValueError(
                f"semantic placeholder <{label}> has no matching dynamic slot")
        ordinal = candidates[0]
        used_ordinals.add(ordinal)
        return f"<VAR{ordinal}>"

    return pattern.sub(replace, source_zh)


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
    if "@" in source and role_source in {"markers", "source-markers"}:
        return None, "source-markers"
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


def _contextual_dynamic_semantic_type(source_template, ordinal):
    token = f"<VAR{int(ordinal)}>"
    match = re.search(re.escape(token), source_template)
    if not match:
        return "unknown"
    before = re.sub(r"\s+", " ", source_template[:match.start()]
                    .replace("@", "").lower())
    after = re.sub(r"\s+", " ", source_template[match.end():]
                   .replace("@", "").lower())
    before = before.rstrip()
    after = after.lstrip()

    if re.search(
            r"\b(?:level|karma|hour|training points|experience points)"
            r"\s+(?:is|are)\s*:?\s*$", before):
        return "numeric_value"
    if (re.search(r"\b(?:cost|costs|price|amount|total)\s*(?:is|:)?\s*$",
                  before)
            or re.match(r"(?:gold\b|extra cards\b|gold pieces\b|"
                        r"coins?\b|(?:yellow|red) potions\b|"
                        r"potions\b|bandages\b|total\b)",
                        after)
            or re.search(r"\b(?:offering of|pieces short|my)\s*$", before)
            and after.startswith("gold")):
        return "number"

    if re.search(r"\b(?:this fine|this good)\s*$", before):
        return "day_period"
    if re.search(r"\bthis\s*$", before) and after.startswith((".", "?", "!", ",")):
        return "day_period"
    if re.search(r"\bsays\s+g'\s*$", before):
        return "greeting_time"
    if re.search(r"\bhave a nice\s*$", before):
        return "greeting_time"
    if re.search(r"\b(?:good|fine)\s*$", before):
        return "greeting_time"
    if re.search(r"\bgood\s+<var\d+>,\s*$", before):
        return "player_name"
    if (before.endswith(("travel", "heading"))
            and (after.startswith("to ") or after.startswith("from "))):
        return "direction"
    if before.endswith("about"):
        return "topic_name"

    if (before.endswith(("careful", "well"))
            or re.search(r"\b(?:aye|ah|fascinating)[!,]?\s*$", before)
            or re.search(r"\bwound,\s*$", before)
            or (not before and re.match(r",\s*your\s+injury\b", after))):
        return "player_name"

    if (not before and re.match(
            r"(?:drinks the potion|receives no enlightenment|has gained)\b",
            after)):
        return "player_name"
    if before.endswith("sellable") or before.endswith("take"):
        return "item_name"
    if before.endswith("the") and re.match(r"(?:\.|!|\?|@|$)", after):
        return "item_name"
    if re.match(r"(?:drinks it|hands you|whispers to you|and\s)", after):
        return "person_name"
    if (before.endswith("does")
            and re.match(r"(?:drink|eat|take|want|need|know)\b", after)):
        return "person_name"
    if re.search(r"(?:poisoned|injury),\s*$", before):
        return "player_name"
    if re.search(r"\b(?:binds|cures)\s*$", before):
        return "person_name"
    if re.match(r"(?:'s hand|'s wounds)", after):
        return "person_name"
    return "unknown"


def classify_contextual_dynamic_slots(source_template, slots):
    """Infer only slot types with a strong, local grammatical cue."""
    classified = []
    for slot in slots:
        current = dict(slot)
        if current.get("semantic_type", "unknown") == "unknown":
            inferred = _contextual_dynamic_semantic_type(
                source_template, current["ordinal"])
            if inferred != "unknown":
                current["semantic_type"] = inferred
                current["semantic_type_source"] = "source-context"
        classified.append(current)
    return classified


def semantic_types_from_expression_variants(lines):
    """Share unanimous contextual or explicit types for each ADDSV origin."""
    observed = {}
    for line in lines:
        source_template = line.get("source_template_en", "")
        for part in line.get("source_parts", []):
            if part.get("kind") != "dynamic":
                continue
            semantic_type = part.get("semantic_type", "unknown")
            if semantic_type == "unknown" and source_template:
                semantic_type = _contextual_dynamic_semantic_type(
                    source_template, part["ordinal"])
            if semantic_type == "unknown":
                continue
            key = (
                int(part["source_func_id"]),
                int(part["source_offset"]),
                int(part["variable_index"]),
            )
            observed.setdefault(key, set()).add(semantic_type)
    return {
        key: next(iter(values))
        for key, values in observed.items()
        if len(values) == 1
    }


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
    source_attribution = re.compile(
        r"^\s*[,;:—–-]?\s*[^.!?]{1,100}\b"
        r"(?:says?|said|asks?|asked|answers?|answered|replies?|replied|"
        r"intones?|intoned|whispers?|whispered|murmurs?|murmured|"
        r"mutters?|muttered|cries?|cried|exclaims?|exclaimed|"
        r"shouts?|shouted|yells?|yelled|states?|stated|adds?|added)\b",
        re.IGNORECASE,
    )
    translated_attribution_boundary = re.compile(
        r"[,，](?=[^,，。！？]{1,50}"
        r"(?:說|道|答|回應|吟誦|低語|呢喃|喊|叫|問|耳語)"
        r"(?:著|道|了|起來)?(?=[。！？]|$))"
    )

    def requires_audio(span):
        return bool(re.search(r"[\w\u3400-\u9fff]", span["text"]))

    source_spans = split_role_text(source_en, explicit_role)
    if not source_spans:
        raise ValueError(f"{line_id}: no usable role spans were identified")

    def translated_spans(text):
        if len(source_spans) == 1:
            clean = _clean_role_text(text)
            return ([{
                "role": source_spans[0]["role"], "text": clean,
                "start_char": 0, "end_char": len(text),
            }] if clean else [])
        spans = split_role_text(text, explicit_role)
        if ([span["role"] for span in spans]
                == [span["role"] for span in source_spans]):
            return spans

        quote_positions = [
            match.start() for match in re.finditer(r"[「『」』]", text)
        ]
        if quote_positions:
            boundaries = [-1, *quote_positions, len(text)]
            quoted = []
            for index, source_span in enumerate(source_spans):
                start = boundaries[index] + 1
                end = boundaries[index + 1]
                value = _clean_role_text(text[start:end])
                if requires_audio({"text": value}):
                    quoted.append({
                        "role": source_span["role"], "text": value,
                        "start_char": start, "end_char": end,
                    })
            if (len(quoted) == len(source_spans)
                    and [span["role"] for span in quoted]
                    == [span["role"] for span in source_spans]):
                return quoted

        marker_positions = [match.start() for match in re.finditer("@", text)]
        if len(marker_positions) == len(source_spans) - 1:
            boundaries = [-1, *marker_positions, len(text)]
            ordered = []
            for index, source_span in enumerate(source_spans):
                start = boundaries[index] + 1
                end = boundaries[index + 1]
                value = _clean_role_text(text[start:end])
                if requires_audio({"text": value}):
                    ordered.append({
                        "role": source_span["role"], "text": value,
                        "start_char": start, "end_char": end,
                    })
            if len(ordered) == len(source_spans):
                return ordered

        spans = []
        cursor = 0

        def append(role, start, end):
            value = _clean_role_text(text[start:end])
            if not value:
                return
            if spans and spans[-1]["role"] == role:
                spans[-1]["text"] += " " + value
                spans[-1]["end_char"] = end
            else:
                spans.append({
                    "role": role, "text": value,
                    "start_char": start, "end_char": end,
                })

        openings = list(re.finditer(r"[「『]", text))
        if openings:
            closers = {"「": "」", "『": "』"}
            for opening in openings:
                append("narrator", cursor, opening.start())
                closing = re.search(
                    re.escape(closers[opening.group()]), text[opening.end():])
                if closing:
                    closing_start = opening.end() + closing.start()
                    closing_end = opening.end() + closing.end()
                    append("speaker", opening.end(), closing_start)
                    cursor = closing_end
                else:
                    append("speaker", opening.end(), len(text))
                    cursor = len(text)
                    break
            append("narrator", cursor, len(text))
            quote_spans = [span for span in spans if requires_audio(span)]
            if ([span["role"] for span in quote_spans]
                    == [span["role"] for span in source_spans]):
                return quote_spans

        has_source_attribution = any(
            source_spans[index - 1]["role"] == "speaker"
            and source_span["role"] == "narrator"
            and source_attribution.search(source_span["text"])
            for index, source_span in enumerate(source_spans)
            if index > 0
        )
        attribution_boundaries = (
            [match.end() for match in
             translated_attribution_boundary.finditer(text)]
            if has_source_attribution else []
        )

        sentence_pieces = []
        cursor = 0
        for piece in re.split(r"(?<=[。！？.!?])", text):
            end = cursor + len(piece)
            piece_boundaries = [
                boundary for boundary in attribution_boundaries
                if cursor < boundary < end
            ]
            piece_starts = [cursor, *piece_boundaries]
            piece_ends = [*piece_boundaries, end]
            for part_start, part_end in zip(piece_starts, piece_ends):
                value = _clean_role_text(text[part_start:part_end])
                if requires_audio({"text": value}):
                    sentence_pieces.append({
                        "text": value, "start_char": part_start,
                        "end_char": part_end,
                    })
            cursor = end

        def source_sentence_count(span):
            clean = _clean_role_text(span["text"])
            count = len(re.findall(r"[.!?。！？]+", clean))
            return max(1, count)

        sentence_counts = [source_sentence_count(span) for span in source_spans]
        if len(sentence_pieces) == sum(sentence_counts):
            aligned = []
            piece_index = 0
            for source_span, count in zip(source_spans, sentence_counts):
                first = sentence_pieces[piece_index]
                last = sentence_pieces[piece_index + count - 1]
                piece_index += count
                value = _clean_role_text(text[first["start_char"]:last["end_char"]])
                if requires_audio({"text": value}):
                    aligned.append({
                        "role": source_span["role"], "text": value,
                        "start_char": first["start_char"],
                        "end_char": last["end_char"],
                    })
            if len(aligned) == len(source_spans):
                return aligned
        return []

    result = []
    for index, source_span in enumerate(source_spans):
        span = {
            "index": index,
            "role": source_span["role"],
            "start_char": source_span["start_char"],
            "end_char": source_span["end_char"],
            "requires_audio": requires_audio(source_span),
            "transcripts": {},
        }
        for gender, transcripts in canonical_by_gender.items():
            en_spans = translated_spans(transcripts["en"])
            zh_spans = translated_spans(transcripts["zh"])
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
                                 callers_of=None, exclusions=None):
    """Build strict dynamic-only JSONL records from disassembled U6 functions."""
    role_records = role_records or {}
    overrides = overrides or {}
    exclusions = exclusions or {}
    if isinstance(role_records, list):
        role_records = {
            _role_lookup_key(row["function_id"], row["offset_key"], row["segment"]): row
            for row in role_records
        }

    records = []
    function_return_types = (
        disassemble_usecode.infer_usecode_function_return_types(functions_data))
    function_arg_counts = {
        int(func["id"]): int(func.get("num_args", 0))
        for func in functions_data
    }
    extracted = []
    for func in functions_data:
        lines = disassemble_usecode.extract_say_lines(
            func, function_return_types=function_return_types,
            function_arg_counts=function_arg_counts)
        extracted.extend((func, line) for line in lines)
    variant_semantic_types = semantic_types_from_expression_variants(
        [line for _func, line in extracted])
    matched_exclusions = set()
    for func, line in extracted:
        npc = disassemble_usecode.get_npc_name(func["id"])
        caller_guess = ""
        if callers_of and not npc:
            caller_guess = disassemble_usecode.infer_speaker_from_callers(
                func["id"], callers_of)

        if not line["has_var"]:
            continue
        line_id = dynamic_line_id(line)
        voice_function_id = int(line.get("voice_func_id", line["func_id"]))
        role_record = role_records.get(_role_lookup_key(
            voice_function_id, line["offset_key"], line["segment"]))
        exclusion = exclusions.get(line_id)
        if exclusion is not None:
            category = str(exclusion.get("category") or "")
            if exclusion.get("source_sha256") != translation_source_sha256(
                    line["source_template_en"]):
                raise ValueError(f"{line_id}: exclusion source hash is stale")
            if (exclusion.get("source_template_en") is not None
                    and exclusion["source_template_en"]
                    != line["source_template_en"]):
                raise ValueError(f"{line_id}: exclusion source text is stale")
            if category == "book_text" and not line["is_book"]:
                raise ValueError(
                    f"{line_id}: book_text exclusion does not match book text")
            if line["is_book"] and category != "book_text":
                raise ValueError(
                    f"{line_id}: dynamic book text requires a book_text exclusion")
            if category == "book_text":
                if exclusion.get("source_template_en") != line["source_template_en"]:
                    raise ValueError(
                        f"{line_id}: book_text exclusion must pin the exact source text")
                if ("@" in line["source_template_en"] or (
                        isinstance(role_record, dict)
                        and str(role_record.get("role") or "").strip().lower()
                        in {"speaker", "narrator", "mixed"})):
                    raise ValueError(
                        f"{line_id}: cannot exclude role-marked or reviewed dialogue as book text")
                matched_exclusions.add(line_id)
                continue
            is_debug_output = (
                exclusion.get("category") == "debug_output"
                and int(exclusion.get("function_id", -1)) == voice_function_id
                and voice_function_id in _DEBUG_OUTPUT_FUNCTIONS
            )
            if exclusion.get("category") == "debug_output" and not is_debug_output:
                raise ValueError(
                    f"{line_id}: debug-output exclusion does not match its audited function")
            if not is_debug_output and ("@" in line["source_template_en"] or (
                    isinstance(role_record, dict)
                    and str(role_record.get("role") or "").strip().lower()
                    in {"speaker", "narrator", "mixed"})):
                raise ValueError(
                    f"{line_id}: cannot exclude role-marked or reviewed dialogue")
            matched_exclusions.add(line_id)
            continue
        if line["is_book"]:
            raise ValueError(
                f"{line_id}: dynamic book text requires an explicit book_text exclusion")
        override = overrides.get(line_id, {})
        if not isinstance(override, dict):
            raise ValueError(f"{line_id}: override must be a JSON object")
        route_override = override.get("speaker_route")
        speaker = str(line.get("speaker") or "").strip()
        speaker_route_source = "usecode-face-tracker" if speaker else ""
        speaker_route_evidence = ""
        if route_override is not None:
            targets = route_override.get("targets") if isinstance(route_override, dict) else None
            source_hash = str(route_override.get("source_sha256") or "") if isinstance(route_override, dict) else ""
            evidence = str(route_override.get("evidence") or "").strip() if isinstance(route_override, dict) else ""
            if (not isinstance(targets, list)
                    or not targets
                    or any(not isinstance(target, str)
                           or not target.strip()
                           or "|" in target
                           for target in targets)
                    or not re.fullmatch(r"[0-9a-f]{64}", source_hash)
                    or source_hash != translation_source_sha256(
                        line["source_template_en"])
                    or not evidence):
                raise ValueError(
                    f"{line_id}: speaker route override is invalid or stale; "
                    "expected nonempty targets, exact source hash, and evidence")
            normalized_targets = list(dict.fromkeys(
                target.strip() for target in targets))
            if speaker and speaker not in normalized_targets:
                raise ValueError(
                    f"{line_id}: speaker route override conflicts with extracted speaker {speaker!r}")
            speaker = "|".join(normalized_targets)
            speaker_route_source = "reviewed-usecode-override"
            speaker_route_evidence = evidence
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
            if slot["semantic_type"] == "unknown":
                origin_key = (
                    int(part["source_func_id"]),
                    int(part["source_offset"]),
                    int(part["variable_index"]),
                )
                inferred = variant_semantic_types.get(origin_key)
                if inferred:
                    slot["semantic_type"] = inferred
                    slot["semantic_type_source"] = "expression-variant"
            slots.append(slot)
        slots = classify_contextual_dynamic_slots(
            line["source_template_en"], slots)
        slots = _merge_slot_overrides(slots, override)
        for slot in slots:
            slot["label"] = _SEMANTIC_SLOT_LABELS.get(
                slot.get("semantic_type"), slot["label"])
            slot.pop("semantic_type_source", None)
        whole_span_override = override.get("whole_span")
        if isinstance(whole_span_override, dict):
            pinned_source_hash = whole_span_override.get("source_sha256")
            if (pinned_source_hash is not None
                    and pinned_source_hash != translation_source_sha256(
                        line["source_template_en"])):
                raise ValueError(
                    f"{line_id}: whole-span source hash is stale")
        source_zh = (override.get("source_template_zh")
                     or disassemble_usecode_translation_lookup(
                         line["source_template_en"], translation_templates,
                         line))
        if source_zh is None:
            if whole_span_override and isinstance(whole_span_override, dict):
                source_zh = whole_span_override.get("zh")
            if source_zh is None:
                raise ValueError(f"{line_id}: missing zh-Hant translation template")
        source_zh = normalize_dynamic_slot_placeholders(source_zh, slots)
        source_zh = sanitize_dynamic_voice_translation(
            line["source_template_en"], source_zh)

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

        classified_source_parts = _apply_classified_slots_to_parts(
            line["source_parts"], slots)
        identity = {
            "function_id": voice_function_id,
            "segment": line["segment"],
            "source_template_en": normalize_translation_source(
                line["source_template_en"]),
            "source_parts": classified_source_parts,
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
            "function_id": voice_function_id,
            "source_function_id": line["func_id"],
            "npc": npc,
            "speaker": speaker,
            "speaker_route_source": speaker_route_source or (
                "caller-inference" if caller_guess else "unresolved"),
            "speaker_route_evidence": speaker_route_evidence,
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
            "source_parts": classified_source_parts,
            "slots": slots,
            "player_gender_variants": gender_variants,
            "canonical_transcripts": canonical,
            "role_source": role_source,
            "role_spans": role_spans,
            "whole_span_override": whole_span_override,
        })

    unmatched_exclusions = sorted(set(exclusions) - matched_exclusions)
    if unmatched_exclusions:
        raise ValueError(
            "unmatched exclusion entries: " + ", ".join(unmatched_exclusions[:8]))
    unique_records = {}
    for row in sorted(records, key=lambda item: (
            item["function_id"], item["offset_key"], item["segment"],
            item["line_id"])):
        key = row["key"]
        previous = unique_records.get(key)
        if previous is None:
            unique_records[key] = row
            continue
        normalized = dict(row, line_id=previous["line_id"])
        if normalized != previous:
            differing_fields = sorted(
                field for field in normalized
                if normalized[field] != previous.get(field))
            raise ValueError(
                f"conflicting duplicate key {key}: "
                f"{previous.get('line_id')} vs {row.get('line_id')} "
                f"(different fields: {', '.join(differing_fields)}; "
                f"types={{{', '.join(field + '=' + repr(previous.get(field)) + '/' + repr(row.get(field)) for field in differing_fields)}}})")
    records = list(unique_records.values())
    validate_dynamic_voice_manifest(records)
    return records


def disassemble_usecode_translation_lookup(source_en, templates, line=None):
    dialogue_keys = [None]
    if line is not None:
        function_id = int(line.get("voice_func_id", line["func_id"]))
        line_key = (
            f"dialogue:0x{function_id:04x}:"
            f"{_offset_key(line['offset_key'])}:{int(line['segment'])}"
        )
        template_hash = translation_source_sha256(source_en)
        template_key = (
            f"dialogue:0x{function_id:04x}:"
            f"fallback_{template_hash[:16]}:0"
        )
        dialogue_keys = [line_key, template_key]
    direct_error = None
    for dialogue_key in dialogue_keys:
        try:
            translated = lookup_zh_translation_template(
                source_en, templates, dialogue_key)
        except ValueError as exc:
            direct_error = exc
            continue
        if translated is not None:
            return translated
    if line is not None:
        composed = _compose_zh_translation_from_parts(line, templates)
        if composed is not None:
            return composed
    if direct_error is not None:
        raise direct_error
    return None


def _compose_zh_translation_from_parts(line, templates):
    """Translate each literal by its original U6 PUSHS/ADDSI source key."""
    parts = line.get("source_parts") or []
    if not parts:
        return None
    translated_parts = []
    for part in parts:
        if part.get("kind") == "dynamic":
            translated_parts.append(f"<VAR{int(part['ordinal'])}>")
            continue
        if part.get("kind") != "literal":
            return None
        key = (
            f"dialogue:0x{int(part['source_func_id']):04x}:"
            f"{int(part['string_offset']):x}:{int(line['segment'])}"
        )
        translated = lookup_zh_translation_template(
            part.get("source_text", part["text"]), templates, key)
        if translated is None:
            source_text = part.get("source_text", part["text"])
            if re.search(r"[\w\u3400-\u9fff]", source_text):
                return None
            translated = re.sub(r"\*+$", "", source_text)
        if "~" in translated:
            translated_segments = [
                segment[0] for segment in
                disassemble_usecode._split_visible_segments_with_ranges(translated)
            ]
            segment_index = int(line["segment"])
            if segment_index >= len(translated_segments):
                return None
            translated = translated_segments[segment_index]
        else:
            translated = re.sub(r"\*+$", "", translated)
        translated_parts.append(translated)
    return "".join(translated_parts)


def _apply_classified_slots_to_parts(source_parts, slots):
    by_ordinal = {int(slot["ordinal"]): slot for slot in slots}
    result = []
    for part in source_parts:
        value = dict(part)
        if value.get("kind") == "dynamic":
            slot = by_ordinal[int(value["ordinal"])]
            value["label"] = slot["label"]
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
            previous_row = next(
                item for item in records[:row_index]
                if item.get("key") == key)
            raise ValueError(
                f"conflicting duplicate key {key}: "
                f"{previous_row.get('line_id')} vs {line_id}")
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


_SUSPICIOUS_SLOT_TAILS = {
    "day_period": ("一天", "一日", "日子", "白天", "今日"),
    "greeting_time": ("日安", "早上", "上午", "中午", "下午", "晚上"),
}


def audit_dynamic_voice_translations(records):
    """Return review-only warnings for suspicious duplicated zh-Hant tails."""
    findings = []
    for row in records:
        translation = str(row.get("source_template_zh") or "")
        line_id = str(row.get("line_id") or "")
        for slot in row.get("slots") or []:
            semantic_type = str(slot.get("semantic_type") or "")
            ordinal = int(slot.get("ordinal", -1))
            if ordinal < 0:
                continue
            token = f"<VAR{ordinal}>"
            for phrase in _SUSPICIOUS_SLOT_TAILS.get(semantic_type, ()):
                pattern = re.compile(
                    r"[。！？!?]\s*" + re.escape(phrase)
                    + r"[。！？!?]*\s*$")
                match = pattern.search(translation)
                if match and token in translation[:match.start()]:
                    findings.append({
                        "line_id": line_id,
                        "language": "zh",
                        "rule": "suspicious-trailing-phrase",
                        "severity": "warning",
                        "text": translation,
                    })
                    break
            else:
                continue
            break
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usecode-file", required=True)
    parser.add_argument("--translation-tsv", required=True)
    parser.add_argument("--overrides")
    parser.add_argument("--roles-manifest")
    parser.add_argument("--exclusions")
    parser.add_argument("--npc-catalog", default=str(DEFAULT_NPC_CATALOG))
    parser.add_argument("--output", required=True)
    parser.add_argument("--check", action="store_true",
                        help="validate and compare with the existing output; never write")
    parser.add_argument("--translation-report",
                        help="write deterministic zh-Hant translation review warnings as UTF-8 JSON")
    args = parser.parse_args(argv)

    functions = _read_functions(args.usecode_file, args.npc_catalog)
    translations = load_zh_translation_templates(args.translation_tsv)
    roles = load_role_records(args.roles_manifest) if args.roles_manifest else {}
    overrides = load_overrides(args.overrides)
    exclusions = load_dynamic_voice_exclusions(args.exclusions)
    callers = disassemble_usecode.build_caller_map({
        func["id"]: func for func in functions
    })
    records = build_dynamic_voice_manifest(
        functions, translations, roles, overrides, callers_of=callers,
        exclusions=exclusions)
    if args.translation_report:
        report_path = Path(args.translation_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(audit_dynamic_voice_translations(records),
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    output = Path(args.output)
    content = _jsonl(records)
    if args.check:
        if not output.is_file():
            raise ValueError(f"--check output does not exist: {output}")
        existing = output.read_text(encoding="utf-8")
        if existing != content:
            raise ValueError(f"manifest is stale: {output}")
        print(
            f"Validated {len(records)} dynamic voice templates and "
            f"{len(exclusions)} explicit exclusions: {output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(
        f"Wrote {len(records)} dynamic voice templates and "
        f"verified {len(exclusions)} explicit exclusions: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2)
