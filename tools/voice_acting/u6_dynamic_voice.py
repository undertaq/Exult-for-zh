"""Canonical source and identity helpers for runtime-composed U6 dialogue."""

from collections import Counter
from hashlib import sha256
import re


def normalize_translation_source(source):
    """Mirror the C++ source normalization used for U6 translation hashes."""
    if isinstance(source, bytes):
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError:
            text = source.decode("latin-1")
    elif isinstance(source, str):
        text = source
    else:
        raise TypeError("source must be str or bytes")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def translation_source_sha256(source):
    """Return the full SHA-256 key used by the U6 translation TSV."""
    normalized = normalize_translation_source(source)
    return sha256(normalized.encode("utf-8")).hexdigest()


def load_zh_translation_templates(tsv_path):
    """Load zh-Hant templates by the full normalized-source SHA-256 column."""
    templates = {}
    with open(tsv_path, "r", encoding="utf-8-sig", newline="") as source_file:
        for line_number, line in enumerate(source_file, 1):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t", 3)
            if len(fields) != 4:
                raise ValueError(f"malformed translation row at {tsv_path}:{line_number}")
            kind, _key, source_hash, translated = fields
            if kind != "dialogue":
                continue
            if not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
                raise ValueError(f"invalid source_sha256 at {tsv_path}:{line_number}")
            normalized_hash = source_hash.lower()
            previous = templates.get(normalized_hash)
            if previous is not None and previous != translated:
                raise ValueError(
                    f"conflicting zh-Hant templates for source hash {normalized_hash}")
            templates[normalized_hash] = translated
    return templates


def lookup_zh_translation_template(source_template_en, templates_by_hash):
    """Return the table's Traditional-Chinese template, or None if absent."""
    return templates_by_hash.get(translation_source_sha256(source_template_en))


def serialize_dynamic_voice_identity(record):
    """Serialize source and role provenance independently of runtime values."""
    fields = [
        "u6-dynamic-voice-v1",
        f"{int(record['function_id']):04x}",
        str(int(record["segment"])),
        normalize_translation_source(record["source_template_en"]),
    ]
    for part in record["source_parts"]:
        kind = part["kind"]
        if kind == "literal":
            fields.extend((
                "part", "literal",
                f"{int(part['source_func_id']):04x}",
                f"{int(part['source_offset']):04x}",
                f"{int(part['string_offset']):04x}",
                normalize_translation_source(part["text"]),
            ))
        elif kind == "dynamic":
            fields.extend((
                "part", "dynamic",
                f"{int(part['source_func_id']):04x}",
                f"{int(part['source_offset']):04x}",
                str(int(part["variable_index"])),
                str(int(part["ordinal"])),
                str(part.get("semantic_type", "unknown")),
            ))
            if part.get("pronoun_form"):
                fields.extend(("pronoun-form", str(part["pronoun_form"])))
        else:
            raise ValueError(f"unsupported source part kind: {kind}")

    for index, role_span in enumerate(record["role_spans"]):
        start = role_span.get("start_char", role_span.get("start_part"))
        end = role_span.get("end_char", role_span.get("end_part"))
        if start is None or end is None:
            raise ValueError("role span must provide character or part boundaries")
        fields.extend((
            "role", str(index), str(role_span["role"]),
            str(int(start)),
            str(int(end)),
        ))

    serialized = bytearray()
    for field in fields:
        encoded = field.encode("utf-8")
        if len(encoded) > 0xFFFFFFFF:
            raise ValueError("dynamic voice identity field exceeds 4 GiB")
        serialized.extend(len(encoded).to_bytes(4, "big"))
        serialized.extend(encoded)
    return bytes(serialized)


def dynamic_voice_key(record):
    """Return a collision-resistant, language-neutral full SHA-256 key."""
    digest = sha256(serialize_dynamic_voice_identity(record)).hexdigest()
    return "dyn_" + digest


_SLOT_TEXT = {
    "player_name": {"en": "Avatar", "zh": "聖者"},
    "honorific": {"en": "milord", "zh": "大人"},
    "number": {"en": "some", "zh": "一些"},
    "person_name": {"en": "that person", "zh": "那個人"},
    "npc_name": {"en": "that person", "zh": "那個人"},
    "place_name": {"en": "that place", "zh": "那個地方"},
    "item_name": {"en": "something", "zh": "某樣東西"},
}

_PRONOUNS = {
    "subject": {"male": {"en": "he", "zh": "他"},
                "female": {"en": "she", "zh": "她"}},
    "object": {"male": {"en": "him", "zh": "他"},
               "female": {"en": "her", "zh": "她"}},
    "possessive_adjective": {"male": {"en": "his", "zh": "他的"},
                              "female": {"en": "her", "zh": "她的"}},
    "possessive_pronoun": {"male": {"en": "his", "zh": "他的"},
                            "female": {"en": "hers", "zh": "她的"}},
    "reflexive": {"male": {"en": "himself", "zh": "他自己"},
                  "female": {"en": "herself", "zh": "她自己"}},
}


def _expected_placeholder_counts(template, field_name):
    all_tokens = re.findall(r"<VAR[^>]*>", template)
    placeholders = re.findall(r"<VAR([0-9]+)>", template)
    if len(all_tokens) != len(placeholders):
        raise ValueError(f"{field_name} contains an invalid dynamic placeholder")
    return Counter(int(value) for value in placeholders)


def _canonical_value(slot, language, player_gender):
    semantic_type = slot.get("semantic_type", "unknown")
    if semantic_type == "pronoun":
        if player_gender not in ("male", "female"):
            raise ValueError("pronoun slot requires player_gender male or female")
        form = slot.get("pronoun_form")
        if not form:
            raise ValueError(
                f"pronoun slot <VAR{slot['ordinal']}> needs a reviewed pronoun_form")
        try:
            return _PRONOUNS[form][player_gender][language]
        except KeyError as exc:
            raise ValueError(f"unsupported pronoun form: {form}") from exc
    if semantic_type == "gender_flag":
        if player_gender not in ("male", "female"):
            raise ValueError("gender_flag slot requires player_gender male or female")
        return {
            "male": {"en": "a man", "zh": "一位男性"},
            "female": {"en": "a woman", "zh": "一位女性"},
        }[player_gender][language]
    if semantic_type not in _SLOT_TEXT:
        raise ValueError(
            f"unknown dynamic slot <VAR{slot['ordinal']}> "
            f"(semantic_type={semantic_type}) needs a reviewed whole-span override")
    return _SLOT_TEXT[semantic_type][language]


def _choose_override_text(override, language, player_gender):
    value = override.get(language)
    if isinstance(value, dict):
        if player_gender is None:
            raise ValueError(f"{language} override requires a player-gender variant")
        value = value.get(player_gender)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"whole-span override is missing reviewed {language} text")
    if re.search(r"<VAR[^>]*>", value):
        raise ValueError(f"whole-span override still contains a dynamic placeholder: {language}")
    return value


def canonicalize_dynamic_template(source_template_en, source_template_zh, slots,
                                  player_gender=None, whole_span_override=None):
    """Create reviewed-safe speech text without inserting runtime slot values."""
    if whole_span_override is not None:
        return {
            "en": _choose_override_text(whole_span_override, "en", player_gender),
            "zh": _choose_override_text(whole_span_override, "zh", player_gender),
        }

    expected_slots = [int(slot["ordinal"]) for slot in slots]
    if sorted(expected_slots) != list(range(len(expected_slots))):
        raise ValueError("dynamic slot ordinals must be unique and contiguous from zero")
    en_counts = _expected_placeholder_counts(source_template_en, "English template")
    zh_counts = _expected_placeholder_counts(source_template_zh, "Traditional Chinese template")
    expected_counts = Counter(expected_slots)
    if en_counts != expected_counts:
        raise ValueError("English template placeholders do not match the ordered slots")
    if zh_counts != en_counts:
        raise ValueError("Traditional Chinese template must preserve slot multiplicity")

    values = {
        int(slot["ordinal"]): {
            "en": _canonical_value(slot, "en", player_gender),
            "zh": _canonical_value(slot, "zh", player_gender),
        }
        for slot in slots
    }

    def replace(template, language):
        result = re.sub(
            r"<VAR([0-9]+)>",
            lambda match: values[int(match.group(1))][language],
            template,
        )
        if re.search(r"<VAR[^>]*>", result):
            raise ValueError(f"unresolved dynamic placeholder remains in {language} transcript")
        return result

    return {
        "en": replace(source_template_en, "en"),
        "zh": replace(source_template_zh, "zh"),
    }
