#!/usr/bin/env python3
"""Ingest FoV companion bark lines into the voice pipeline.

Pattern (FoV-only helper chain 0x8FF -> 0x900 -> 0x903):
    pushi <npc>            ; speaker (often)
    pushs "<text>"         ; @...@ delimited bark/conversation text
    call [extern 0x08FF]

extract_say_lines only captures addsi->say sequences, so these lines were
never extracted: no review row, no EN pairing, no voice clips, and dual mode
shows ZH only.

For every function this script aligns the ordered bark lists of usecode.zh
and usecode.en (same compiled structure) and appends rows to
en_voice_lines.csv / zh_voice_lines.csv / bilingual_mapping_review.json:

  offset_key = hex of the pushs data offset (matches the runtime fallback
  added in ucinternal.cc, where a say with no current-function addsi falls
  back to the last PUSHS entry of the trace).

Idempotent: (func_id, offset_key, segment) already present anywhere is kept.
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import disassemble_usecode as dis
from npc_data import NPC_NUMBERS

ZH_USECODE = SCRIPT_DIR / "_live" / "usecode.zh"
EN_USECODE = SCRIPT_DIR / "_live" / "usecode.en"
EN_CSV = SCRIPT_DIR / "en_voice_lines.csv"
ZH_CSV = SCRIPT_DIR / "zh_voice_lines.csv"
MAPPING = SCRIPT_DIR / "bilingual_mapping_review.json"
BACKUP = SCRIPT_DIR / "bilingual_mapping_review.json.pre_barks"

BARK_EXTERN = 0x08FF
NAME_BY_NUM = {num: name for name, num in NPC_NUMBERS.items()}


def parse_functions(blob):
    funcs = {}
    offset = dis.skip_symbol_table(blob, 0)
    while offset < len(blob):
        try:
            fid, fdata, ext, nxt = dis.parse_function(blob, offset)
        except Exception:
            break
        if nxt <= offset:
            break
        funcs[fid] = (fdata, ext, nxt)
        offset = nxt
    return funcs


def split_parts(fdata, extended):
    pos = 0
    dl = dis.read4s(fdata, pos) if extended else dis.read2(fdata, pos)
    pos += 4 if extended else 2
    old_data = fdata[pos:pos + dl]
    pos += dl
    return old_data


def extern_table(fdata, extended):
    """{index: func_id} for this function's extern table."""
    pos = 0
    dl = dis.read4s(fdata, pos) if extended else dis.read2(fdata, pos)
    pos += 4 if extended else 2
    pos += dl
    pos += 4          # nargs + nvars
    nx = dis.read2(fdata, pos)
    pos += 2
    out = {}
    for i in range(nx):
        if pos + 2 > len(fdata):
            break
        out[i] = dis.read2(fdata, pos + i * 2)
    return out


def undo_mojibake(raw):
    return raw.encode("latin-1", errors="surrogateescape").decode(
        "utf-8", errors="surrogateescape")


def extract_barks(fid, blob, functions):
    """Ordered [(data_off, text, speaker_npc_or_None)] for one function.

    A bark is ONLY a pushs immediately followed by call [extern 0x08FF]
    (+ optional pushi <npc> / calli 4 right before it). Topic keywords
    (pushs -> calli add_answer) and say traces are not touched.
    """
    if fid not in functions:
        return []
    fdata, ext, _ = functions[fid]
    data_seg = split_parts(fdata, ext)
    externs = extern_table(fdata, ext)

    def text_at(off):
        end = data_seg.find(b"\0", off)
        if end < 0:
            end = len(data_seg)
        return undo_mojibake(data_seg[off:end].decode("latin-1", errors="surrogateescape"))

    func = dis.disassemble_function(fid, fdata, ext)
    instrs = func["instructions"]
    barks = []
    last_pushi = None
    for i, (addr, raw, name, params, comment) in enumerate(instrs):
        if name == "pushi" and params:
            last_pushi = params[0]
            continue
        is_bark_call = (
            name == "call"
            and params
            and externs.get(params[0]) == BARK_EXTERN
        )
        if not is_bark_call:
            continue
        # previous instruction must be the pushs carrying the text
        if i == 0 or instrs[i - 1][2] != "pushs":
            continue
        off = instrs[i - 1][3][0]
        text = text_at(off).strip()
        if text.startswith("@") and text.endswith("@") and len(text) >= 2:
            text = text[1:-1].strip()
        if not text:
            continue
        speaker = None
        # speaker npc: a negative pushi shortly before the bark. An
        # intervening single calli/callis is fine (e.g.
        # pushi -288 ; calli 4 ; pushs ; call 08FF -> Bollux).
        j = i - 2
        steps = 0
        while j >= 0 and steps < 5:
            n3, p3 = instrs[j][2], instrs[j][3]
            if n3 == "pushi" and p3 and p3[0] < 0:
                cand = abs(p3[0])
                if cand in NAME_BY_NUM:
                    speaker = NAME_BY_NUM[cand]
                break
            if n3 == "say":
                break
            j -= 1
            steps += 1
        barks.append((off, text, speaker))
    return barks


def csv_row(func_hex, npc, offset_hex, text):
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="").writerow(
        [func_hex, npc, "", "", offset_hex, 0, 1, "False", text]
    )
    return buf.getvalue()


def append_csv(path, rows):
    have = set()
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                have.add((r["func_id"].upper(), r["offset_key"].lower(), r["segment"]))
    raw = path.read_bytes()
    nl = b"\r\n" if b"\r\n" in raw[:2000] else b"\n"
    added = []
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    for func_hex, npc, offset_hex, text in rows:
        key = (func_hex.upper(), offset_hex.lower(), "0")
        if key in have:
            continue
        w.writerow([func_hex, npc, "", "", offset_hex, 0, 1, "False", text])
        added.append(key)
    with open(path, "ab") as f:
        if raw and not raw.endswith(nl):
            f.write(nl)
        f.write(buf.getvalue().encode("utf-8"))
    return added


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    zh_blob = ZH_USECODE.read_bytes()
    en_blob = EN_USECODE.read_bytes() if EN_USECODE.exists() else None
    zh_funcs = parse_functions(zh_blob)
    en_funcs = parse_functions(en_blob) if en_blob else {}

    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    have_json = {
        (r.get("en_func_id", "").upper(), r.get("en_offset_key", "").lower())
        for r in mapping
    }

    new_csv_en, new_csv_zh, new_json = [], [], []
    stats = {"funcs": 0, "pairs": 0, "skipped_no_pair": 0}
    for fid, (fdata, ext, _) in sorted(zh_funcs.items()):
        zh_barks = extract_barks(fid, zh_blob, zh_funcs)
        if not zh_barks:
            continue
        en_barks = extract_barks(fid, en_blob, en_funcs) if en_funcs else []
        func_hex = "0x%04X" % fid
        touched = False
        for k, (off, ztext, speaker) in enumerate(zh_barks):
            key_hex = "%x" % off
            if (func_hex.upper(), key_hex) in have_json:
                continue
            etext = en_barks[k][1] if k < len(en_barks) else ""
            if not etext:
                stats["skipped_no_pair"] += 1
                continue
            npc = speaker or "UNKNOWN"
            new_csv_en.append((func_hex, npc, key_hex, etext))
            new_csv_zh.append((func_hex, npc, key_hex, ztext))
            new_json.append({
                "npc": npc,
                "en_func_id": func_hex,
                "en_offset_key": key_hex,
                "en_segment": 0,
                "zh_func_id": func_hex,
                "zh_offset_key": key_hex,
                "zh_segment": 0,
                "en_text": etext,
                "zh_text": ztext,
            })
            have_json.add((func_hex.upper(), key_hex))
            touched = True
            stats["pairs"] += 1
        if touched:
            stats["funcs"] += 1

    print(f"functions touched : {stats['funcs']}")
    print(f"bark pairs added  : {stats['pairs']}  (unpaired zh-only: {stats['skipped_no_pair']})")
    if args.dry_run:
        for r in new_json[:12]:
            print("  ", r["npc"], r["en_func_id"], r["en_offset_key"],
                  "|", r["zh_text"][:36], "|", r["en_text"][:40])
        return 0

    if BACKUP.exists() is False:
        import shutil
        shutil.copy2(MAPPING, BACKUP)

    added_en = append_csv(EN_CSV, new_csv_en)
    added_zh = append_csv(ZH_CSV, new_csv_zh)
    print("en_voice_lines.csv added:", len(added_en))
    print("zh_voice_lines.csv added:", len(added_zh))

    mapping.extend(new_json)
    MAPPING.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("mapping json: appended", len(new_json), "bark rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
