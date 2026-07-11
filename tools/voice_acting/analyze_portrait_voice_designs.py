#!/usr/bin/env python3
"""Use a local Ollama vision model to improve NPC voice design prompts."""
import argparse
import base64
import json
import re
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
DESIGNS_PATH = SCRIPT_DIR / "npc_voice_designs.json"
MAPPING_PATH = SCRIPT_DIR / "bilingual_mapping_review.json"
PORTRAITS_DIR = SCRIPT_DIR / "voice_casting_tool" / "data" / "portraits"
REFS_DIR = PROJECT_DIR / "voice" / "refs"
BACKUP_DIR = PROJECT_DIR / "voice_backup"
REPORT_PATH = SCRIPT_DIR / "portrait_voice_design_report.json"
OLLAMA_URL = "http://localhost:11434/api/chat"


def normalize_name(name):
    value = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    if value.endswith("u7"):
        value = value[:-2]
    return value


def build_portrait_index(portraits_dir):
    index = {}
    for path in sorted(Path(portraits_dir).iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif"}:
            continue
        key = normalize_name(path.stem)
        index.setdefault(key, path)
    return index


def portrait_name_variants(name):
    base = normalize_name(name)
    variants = [base]
    for prefix in ("lord",):
        if base.startswith(prefix) and len(base) > len(prefix):
            variants.append(base[len(prefix):])
    return [variant for variant in variants if variant]


def find_portrait_for_name(name, portrait_index):
    variants = portrait_name_variants(name)
    for variant in variants:
        portrait = portrait_index.get(variant)
        if portrait:
            return portrait
    for key, portrait in portrait_index.items():
        for variant in variants:
            if key.startswith(variant) or variant.startswith(key):
                return portrait
    return None


def select_portrait_for_design(design, portrait_index):
    portraits = select_portraits_for_design(design, portrait_index)
    return portraits[0] if portraits else None


def select_portraits_for_design(design, portrait_index):
    portraits = []
    seen = set()
    for npc in design.get("npcs", []):
        portrait = find_portrait_for_name(npc, portrait_index)
        if portrait and portrait not in seen:
            portraits.append(portrait)
            seen.add(portrait)
    if not portraits:
        portrait = find_portrait_for_name(design.get("npc", ""), portrait_index)
        if portrait:
            portraits.append(portrait)
    return portraits


def extract_json_object(text):
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"model response did not contain JSON object: {text[:160]}")
    return text[start:end + 1]


def parse_model_json(text):
    return json.loads(extract_json_object(text))


def load_mapping_samples(mapping_path, max_samples=3):
    samples = {}
    if not Path(mapping_path).exists():
        return samples
    rows = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
    for row in rows:
        names = []
        for key in ("speaker", "npc"):
            value = (row.get(key) or "").strip()
            if value and value not in names:
                names.append(value)
        text = (row.get("en_text") or row.get("zh_text") or "").strip()
        if not text:
            continue
        text = re.sub(r"\s+", " ", text)
        for name in names:
            bucket = samples.setdefault(name, [])
            if len(bucket) < max_samples and text not in bucket:
                bucket.append(text)
    return samples


def build_prompt(design_id, design, dialogue_samples):
    npc = design.get("npc") or design_id
    npcs = design.get("npcs", [])
    sample_lines = []
    for name in npcs[:4]:
        for line in dialogue_samples.get(name, [])[:2]:
            if line not in sample_lines:
                sample_lines.append(line)
            if len(sample_lines) >= 5:
                break
        if len(sample_lines) >= 5:
            break
    sample_text = "\n".join(f"- {line[:220]}" for line in sample_lines) or "- No dialogue sample available."
    return f"""You are designing text-to-speech casting for an Ultima VII NPC.
Use the portrait and dialogue samples to infer a better voice direction.
Do not mention the portrait or image in the voice description.
Avoid modern announcer, radio, audiobook, or theatrical overacting.
Return only compact JSON with keys:
apparent_age, gender_presentation, visual_traits, temperament, voice_desc_en.

NPC/design: {npc}
Current English voice description: {design.get('voice_desc_en', '')}
Reference English text: {design.get('ref_en_text', '')}
Dialogue samples:
{sample_text}

voice_desc_en must be one fluent TTS instruction, 12 to 28 words, describing age, vocal texture, pace, warmth, and authority if appropriate."""


def call_ollama(model, image_path, prompt, timeout):
    image_paths = image_path if isinstance(image_path, (list, tuple)) else [image_path]
    images_b64 = [
        base64.b64encode(Path(path).read_bytes()).decode("ascii")
        for path in image_paths
    ]
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": images_b64,
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 220,
        },
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = json.loads(response.read())
    return raw.get("message", {}).get("content", "")


def infer_gender(design, analysis):
    explicit = " ".join([
        analysis.get("gender_presentation", ""),
        design.get("voice_desc_en", ""),
        design.get("voice_desc_zh", ""),
    ]).strip().lower()
    design_context = " ".join([
        design.get("voice_desc_en", ""),
        design.get("voice_desc_zh", ""),
        design.get("ref_en_text", ""),
    ]).strip().lower()
    retained_identity = re.search(
        r"(?:^|retain character context:\s*)(creature|entity|neutral)\b",
        design_context,
    )
    if retained_identity:
        return "生物" if retained_identity.group(1) == "creature" else "中性"
    if re.search(r"^(male|masculine)\b", explicit) or re.search(r"\bclearly masculine\b", explicit):
        return "男性"
    if re.search(r"^(female|feminine)\b", explicit) or re.search(r"\bclearly feminine\b", explicit):
        return "女性"
    text = " ".join([
        analysis.get("gender_presentation", ""),
        analysis.get("voice_desc_en", ""),
        design.get("voice_desc_en", ""),
        design.get("voice_desc_zh", ""),
        design.get("ref_en_text", ""),
    ]).lower()
    if any(word in text for word in ("female", "woman", "girl", "actress", "feminine")) or "女性" in text:
        return "女性"
    if any(word in text for word in ("male", "man", "boy", "actor", "masculine")) or "男性" in text:
        return "男性"
    if any(word in text for word in ("creature", "monster", "dragon", "hydra")):
        return "生物"
    return "中性"


def infer_age(design, analysis):
    text = " ".join([
        analysis.get("apparent_age", ""),
        analysis.get("voice_desc_en", ""),
        design.get("voice_desc_en", ""),
        design.get("voice_desc_zh", ""),
    ]).lower()
    if re.search(r"\b(child|little girl|little boy|young girl|young boy|toddler)\b", text) or "小孩" in text:
        return "小孩"
    if "20s-40s" in text or ("20s" in text and "40s" in text):
        return "20-40歲"
    if "20s-30s" in text or ("20s" in text and "30s" in text):
        return "20-30歲"
    if "30s-50s" in text or ("30s" in text and "50s" in text):
        return "30-50歲"
    if "30s-40s" in text or ("30s" in text and "40s" in text):
        return "30-40歲"
    if any(word in text for word in ("middle", "30s", "40s", "50s", "thirties", "forties", "fifties", "mature", "mid-thirties")):
        return "中年"
    if re.search(r"\b(young|youth|20s|twenties|teen|teenage)\b", text):
        return "年輕"
    if any(word in text for word in ("elderly", "old", "aged", "ancient")):
        return "年長"
    return "成年"


def chinese_style_phrase(text):
    text = (text or "").lower()
    phrases = []
    keyword_phrases = [
        (("warm", "friendly", "kind", "gentle"), "溫暖友善"),
        (("playful", "mischievous", "theatrical", "performer"), "活潑有戲劇感"),
        (("authoritative", "commanding", "firm", "serious"), "沉穩有權威感"),
        (("deep", "resonant", "gravelly", "raspy", "gruff"), "低沉有質感"),
        (("soft", "soothing", "tender"), "柔和"),
        (("slow", "measured", "deliberate"), "語速沉穩"),
        (("quick", "energetic", "lively"), "語氣有活力"),
        (("wise", "wisdom", "experienced"), "帶有智慧與閱歷"),
        (("sad", "melancholic", "worried", "anxious"), "帶有憂慮感"),
    ]
    for keys, phrase in keyword_phrases:
        if any(key in text for key in keys) and phrase not in phrases:
            phrases.append(phrase)
    if not phrases:
        phrases.append("自然清晰")
    return "，".join(phrases[:4])


def infer_speaking_pace(design, analysis, en_desc):
    text = " ".join([
        analysis.get("temperament", ""),
        analysis.get("voice_desc_en", ""),
        design.get("voice_desc_en", ""),
        design.get("voice_desc_zh", ""),
        en_desc,
    ]).lower()
    if any(word in text for word in ("quick", "fast", "brisk", "energetic", "lively", "hurried", "agile", "playful", "theatrical")):
        return (
            "speaking pace: brisk, lively, with expressive timing",
            "語速偏快，節奏活潑且富表情",
        )
    if any(word in text for word in ("slow", "measured", "deliberate", "solemn", "regal", "elderly", "ancient", "wise", "dignified")):
        return (
            "speaking pace: slow and measured, with deliberate pauses",
            "語速偏慢，停頓沉穩",
        )
    if any(word in text for word in ("anxious", "worried", "nervous", "tense")):
        return (
            "speaking pace: uneven and slightly tense, with occasional quick phrases",
            "語速略不均勻，帶緊張感",
        )
    return (
        "speaking pace: natural medium tempo, clear and steady",
        "語速自然中等，清晰穩定",
    )


def infer_pitch_prompt(design, analysis, en_desc):
    gender = infer_gender(design, analysis)
    age = infer_age(design, analysis)
    text = " ".join([
        analysis.get("voice_desc_en", ""),
        design.get("voice_desc_en", ""),
        design.get("voice_desc_zh", ""),
        en_desc,
    ]).lower()
    if any(word in text for word in ("creature", "monster", "dragon", "hydra", "demon", "rumbling")) or gender == "生物":
        return (
            "pitch: very low, rumbling creature register",
            "音高很低，帶轟鳴感的生物聲線",
        )
    if any(word in text for word in ("high-pitched", "little girl", "little boy", "child", "young girl", "young boy")) or age == "小孩":
        return (
            "pitch: high, bright childlike range",
            "音高偏高，明亮童聲",
        )
    if any(word in text for word in ("deep", "baritone", "bass", "resonant", "gravelly", "gruff", "raspy", "low")):
        return (
            "pitch: low, resonant chest voice",
            "音高偏低，胸腔共鳴明顯",
        )
    if gender == "女性":
        return (
            "pitch: medium-high, clear feminine range",
            "音高偏高，清晰女性聲線",
        )
    if gender == "男性":
        return (
            "pitch: medium-low, clear masculine range",
            "音高中低，清晰男性聲線",
        )
    return (
        "pitch: medium, balanced neutral range",
        "音高中等，中性平衡",
    )


def build_chinese_description(design, analysis, en_desc):
    gender = infer_gender(design, analysis)
    age = infer_age(design, analysis)
    style = chinese_style_phrase(" ".join([
        analysis.get("voice_desc_en", ""),
        design.get("voice_desc_en", ""),
        en_desc,
    ]))
    _, zh_pace = infer_speaking_pace(design, analysis, en_desc)
    _, zh_pitch = infer_pitch_prompt(design, analysis, en_desc)
    details = re.sub(r"\s+", " ", (en_desc or "").strip())
    if details:
        return f"{gender}，{age}，{style}，{zh_pace}，{zh_pitch}，角色音色細節：{details}，用標準的普通話朗讀"
    return f"{gender}，{age}，{style}，{zh_pace}，{zh_pitch}，用標準的普通話朗讀"


def build_updated_descriptions(design, analysis):
    model_desc = re.sub(r"\s+", " ", (analysis.get("voice_desc_en") or "").strip())
    old_en = re.sub(r"\s+", " ", (design.get("voice_desc_en") or "").strip())
    traits = re.sub(r"\s+", " ", (analysis.get("visual_traits") or "").strip())

    parts = []
    if model_desc:
        parts.append(model_desc.rstrip("."))
    if old_en and old_en.lower() not in model_desc.lower():
        parts.append(f"retain character context: {old_en.rstrip('.')}")
    if traits:
        parts.append(f"visible traits: {traits.rstrip('.')}")
    en_desc = "; ".join(parts)
    if en_desc:
        en_desc = en_desc[0].upper() + en_desc[1:]
        en_pace, _ = infer_speaking_pace(design, analysis, en_desc)
        if "speaking pace:" not in en_desc.lower():
            en_desc = f"{en_desc}; {en_pace}"
        en_pitch, _ = infer_pitch_prompt(design, analysis, en_desc)
        if "pitch:" not in en_desc.lower():
            en_desc = f"{en_desc}; {en_pitch}"

    zh_desc = build_chinese_description(design, analysis, en_desc) if en_desc else (design.get("voice_desc_zh") or "").strip()
    return en_desc, zh_desc


def apply_analysis(designs, design_id, portrait_path, analysis, model):
    design = designs["designs"][design_id]
    old_en = design.get("voice_desc_en", "")
    old_zh = design.get("voice_desc_zh", "")
    new_en, new_zh = build_updated_descriptions(design, analysis)
    if not new_en:
        return False
    design["voice_desc_en"] = new_en
    design["voice_desc_zh"] = new_zh
    portrait_paths = portrait_path if isinstance(portrait_path, (list, tuple)) else [portrait_path]
    portrait_names = [Path(path).name for path in portrait_paths]
    design["_portrait_voice_analysis"] = {
        "model": model,
        "portrait": portrait_names[0] if portrait_names else "",
        "portraits": portrait_names,
        "apparent_age": analysis.get("apparent_age", ""),
        "gender_presentation": analysis.get("gender_presentation", ""),
        "visual_traits": analysis.get("visual_traits", ""),
        "temperament": analysis.get("temperament", ""),
        "voice_desc_en": new_en,
        "previous_voice_desc_en": old_en,
        "previous_voice_desc_zh": old_zh,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return old_en != new_en or old_zh != new_zh


def backup_current_assets():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    design_backup = BACKUP_DIR / f"npc_voice_designs_before_vision_{stamp}.json"
    shutil.copy2(DESIGNS_PATH, design_backup)
    refs_backup = None
    if REFS_DIR.exists():
        refs_backup = BACKUP_DIR / f"refs_before_vision_{stamp}"
        shutil.copytree(REFS_DIR, refs_backup)
    return design_backup, refs_backup


def iter_designs(designs, npc_filter=None, unique_only=False):
    wanted = {name.strip().lower() for name in (npc_filter or []) if name.strip()}
    for design_id, design in sorted(designs.get("designs", {}).items()):
        npcs = design.get("npcs", [])
        if wanted and not ({n.lower() for n in npcs} & wanted or (design.get("npc", "").lower() in wanted)):
            continue
        if unique_only and design.get("type") != "unique":
            continue
        yield design_id, design


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen2.5vl:7b", help="Ollama vision model")
    parser.add_argument("--npc", default="", help="Comma-separated NPC names to process")
    parser.add_argument("--limit", type=int, default=None, help="Maximum designs to analyze")
    parser.add_argument("--timeout", type=int, default=360, help="Per-request timeout in seconds")
    parser.add_argument("--apply", action="store_true", help="Write updated npc_voice_designs.json")
    parser.add_argument("--backup", action="store_true", help="Backup designs and voice/refs before writing")
    parser.add_argument("--force", action="store_true", help="Re-analyze designs that already have portrait metadata")
    parser.add_argument("--unique-only", action="store_true", help="Only process unique NPC designs")
    args = parser.parse_args()

    designs = json.loads(DESIGNS_PATH.read_text(encoding="utf-8"))
    portraits = build_portrait_index(PORTRAITS_DIR)
    samples = load_mapping_samples(MAPPING_PATH)
    npc_filter = [x.strip() for x in args.npc.split(",") if x.strip()]

    if args.apply and args.backup:
        design_backup, refs_backup = backup_current_assets()
        print(f"Backed up designs: {design_backup}")
        if refs_backup:
            print(f"Backed up refs: {refs_backup}")

    report = {
        "model": args.model,
        "apply": args.apply,
        "processed": [],
        "missing_portraits": [],
        "errors": [],
    }
    changed = 0
    processed = 0

    for design_id, design in iter_designs(designs, npc_filter, args.unique_only):
        if args.limit is not None and processed >= args.limit:
            break
        if design.get("_portrait_voice_analysis") and not args.force:
            continue
        design_portraits = select_portraits_for_design(design, portraits)
        if not design_portraits:
            report["missing_portraits"].append({"design_id": design_id, "npcs": design.get("npcs", [])})
            continue

        prompt = build_prompt(design_id, design, samples)
        portrait_names = [portrait.name for portrait in design_portraits]
        print(f"[{design_id}] analyzing {', '.join(portrait_names)}")
        start = time.time()
        try:
            response = call_ollama(args.model, design_portraits, prompt, args.timeout)
            analysis = parse_model_json(response)
            elapsed = round(time.time() - start, 1)
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            print(f"  ERROR: {exc}")
            report["errors"].append({"design_id": design_id, "portraits": portrait_names, "error": str(exc)})
            processed += 1
            continue

        entry = {
            "design_id": design_id,
            "npc": design.get("npc", ""),
            "npcs": design.get("npcs", []),
            "portrait": portrait_names[0],
            "portraits": portrait_names,
            "elapsed_seconds": elapsed,
            "analysis": analysis,
        }
        if args.apply:
            did_change = apply_analysis(designs, design_id, design_portraits, analysis, args.model)
            entry["changed"] = did_change
            changed += int(did_change)
        report["processed"].append(entry)
        processed += 1
        print(f"  {analysis.get('voice_desc_en', '').strip()}")

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.apply:
        DESIGNS_PATH.write_text(json.dumps(designs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Updated {DESIGNS_PATH}: {changed} changed design(s)")
    else:
        print("Dry run only; npc_voice_designs.json was not modified")
    print(f"Wrote report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
