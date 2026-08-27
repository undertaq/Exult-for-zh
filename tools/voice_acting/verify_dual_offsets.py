#!/usr/bin/env python3
"""
Verification program to compare usecode.zh vs usecode.dual binary structures
and show exactly how/where func_id, offset_key, segment change.
"""

import sys
import json
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import disassemble_usecode as dis


def extract_data_segment(data_segment):
    """Extract all entries from the data segment: strings and null bytes."""
    entries = []  # (offset, type, value) where type is 'str' or 'null'
    i = 0
    while i < len(data_segment):
        if data_segment[i] != 0:
            start = i
            while i < len(data_segment) and data_segment[i] != 0:
                i += 1
            text = data_segment[start:i].decode("latin-1")
            entries.append((start, "str", text))
        else:
            entries.append((i, "null", None))
        i += 1
    return entries


def extract_say_lines(func):
    """Extract all say-string lines from a function."""
    lines = []
    accum = []
    
    for addr, raw_bytes, name, params, comment in func['instructions']:
        if name == 'addsi' and params:
            offset = params[0]
            text = func['strings'].get(offset, "")
            accum.append(('addsi', offset, text))
        elif name == 'addsv' and params:
            accum.append(('addsv', params[0], None))
        elif name == 'say':
            if not accum:
                continue

            # Build the offset key (only addsi offsets)
            addsi_offsets = [hex(e[1]) for e in accum if e[0] == 'addsi']
            offset_key = "_".join(addsi_offsets)

            # Build the template text with labeled placeholders
            template_parts = []
            has_var = False
            addsv_labels = []
            for typ, val, text in accum:
                if typ == 'addsi':
                    template_parts.append(text)
                else:
                    template_parts.append("<VAR>")
                    addsv_labels.append("<VAR>")
                    has_var = True
            full_template = "".join(template_parts)

            # Split at ~~ to get individual displayed segments
            segments = []
            current = full_template
            while current:
                current = current.lstrip('*')
                if not current:
                    break
                tilde_pos = current.find('~')
                if tilde_pos == -1:
                    segments.append(current.rstrip('*'))
                    break
                segment = current[:tilde_pos].rstrip('*')
                if segment:
                    segments.append(segment)
                current = current[tilde_pos + 1:]
                if current.startswith('~'):
                    current = current[1:]

            for seg_idx, seg_text in enumerate(segments):
                lines.append({
                    'func_id': func['id'],
                    'offset_key': offset_key,
                    'segment': seg_idx,
                    'total_segments': len(segments),
                    'text': seg_text,
                    'has_var': has_var,
                    'addsv_labels': addsv_labels,
                    'addsi_offsets': [e[1] for e in accum if e[0] == 'addsi'],
                    'code_addr': addr,
                })

            accum = []
        elif name in ('ret', 'abrt'):
            accum = []

    return lines


def disassemble_all_functions(blob):
    """Disassemble every function in a usecode blob: {fid: func_dict}."""
    funcs = {}
    offset = 0
    while offset < len(blob):
        sym_next = dis.skip_symbol_table(blob, offset)
        if sym_next > offset:
            offset = sym_next
            continue
        try:
            fid, fdata, ext, nxt = dis.parse_function(blob, offset)
        except (struct.error, IndexError):
            break
        if nxt <= offset:
            break
        try:
            funcs[fid] = dis.disassemble_function(fid, fdata, ext)
        except (struct.error, IndexError, ValueError):
            pass
        offset = nxt
    return funcs


def analyze_function(func, func_id):
    """Analyze a function's say lines and return key info."""
    lines = extract_say_lines(func)
    results = []
    for line in lines:
        results.append({
            'func_id': f"0x{func_id:04X}",
            'offset_key': line['offset_key'],
            'segment': line['segment'],
            'text_preview': line['text'][:80] + ("..." if len(line['text']) > 80 else ""),
            'addsi_offsets': [f"0x{o:04X}" for o in line['addsi_offsets']],
            'code_addr': f"0x{line['code_addr']:04X}",
        })
    return results


def compare_functions(zh_blob, dual_blob, review_path=None):
    """Compare say lines between zh and dual binaries."""
    zh_funcs = disassemble_all_functions(zh_blob)
    dual_funcs = disassemble_all_functions(dual_blob)
    
    # Load review JSON for context
    review_map = {}
    if review_path and Path(review_path).exists():
        with open(review_path, 'r', encoding='utf-8') as f:
            review = json.load(f)
        for r in review:
            key = (r.get('zh_func_id', '').lower(), r.get('zh_offset_key', ''), r.get('zh_segment'))
            review_map[key] = r
    
    print(f"\n{'='*100}")
    print(f"COMPARISON: usecode.zh vs usecode.dual")
    print(f"{'='*100}")
    print(f"usecode.zh functions: {len(zh_funcs)}")
    print(f"usecode.dual functions: {len(dual_funcs)}")
    
    all_fids = set(zh_funcs.keys()) | set(dual_funcs.keys())
    
    changes = {
        'same': 0,
        'offset_key_changed': 0,
        'segment_changed': 0,
        'new_in_dual': 0,
        'missing_in_dual': 0,
        'text_changed': 0,
    }
    
    for fid in sorted(all_fids):
        zh_func = zh_funcs.get(fid)
        dual_func = dual_funcs.get(fid)
        
        if zh_func and dual_func:
            zh_lines = analyze_function(zh_func, fid)
            dual_lines = analyze_function(dual_func, fid)
            
            # Match by code_addr and segment
            zh_by_loc = {(l['code_addr'], l['segment']): l for l in zh_lines}
            dual_by_loc = {(l['code_addr'], l['segment']): l for l in dual_lines}
            
            all_locs = set(zh_by_loc.keys()) | set(dual_by_loc.keys())
            
            for loc in sorted(all_locs):
                zh_l = zh_by_loc.get(loc)
                dual_l = dual_by_loc.get(loc)
                
                if zh_l and dual_l:
                    # Check if offset_key changed
                    if zh_l['offset_key'] != dual_l['offset_key']:
                        changes['offset_key_changed'] += 1
                        print(f"\n  OFFSET_KEY CHANGED: func={zh_l['func_id']} seg={zh_l['segment']} code={zh_l['code_addr']}")
                        print(f"    zh:     offset_key={zh_l['offset_key']}")
                        print(f"    dual:   offset_key={dual_l['offset_key']}")
                        print(f"    zh addsi:  {zh_l['addsi_offsets']}")
                        print(f"    dual addsi: {dual_l['addsi_offsets']}")
                        print(f"    text: {zh_l['text_preview'].encode('ascii', 'replace').decode()}")
                        
                        # Check review for expected mapping
                        rev_key = (zh_l['func_id'].lower(), zh_l['offset_key'], zh_l['segment'])
                        if rev_key in review_map:
                            r = review_map[rev_key]
                            print(f"    REVIEW: en_func_id={r.get('en_func_id')} en_offset_key={r.get('en_offset_key')} en_segment={r.get('en_segment')}")
                    
                    # Check if text changed (merged)
                    elif zh_l['text_preview'] != dual_l['text_preview']:
                        changes['text_changed'] += 1
                        print(f"\n  TEXT CHANGED (merged): func={zh_l['func_id']} seg={zh_l['segment']} code={zh_l['code_addr']}")
                        print(f"    zh:   {zh_l['text_preview'].encode('ascii', 'replace').decode()}")
                        print(f"    dual: {dual_l['text_preview'].encode('ascii', 'replace').decode()}")
                    else:
                        changes['same'] += 1
                        
                elif zh_l and not dual_l:
                    changes['missing_in_dual'] += 1
                    print(f"\n  MISSING IN DUAL: func={zh_l['func_id']} seg={zh_l['segment']} code={zh_l['code_addr']}")
                    print(f"    offset_key={zh_l['offset_key']} text={zh_l['text_preview'].encode('ascii', 'replace').decode()}")
                    
                elif dual_l and not zh_l:
                    changes['new_in_dual'] += 1
                    print(f"\n  NEW IN DUAL: func={dual_l['func_id']} seg={dual_l['segment']} code={dual_l['code_addr']}")
                    print(f"    offset_key={dual_l['offset_key']} text={dual_l['text_preview'].encode('ascii', 'replace').decode()}")
    
    print(f"\n{'='*100}")
    print("SUMMARY:")
    print(f"  Same (no change):           {changes['same']}")
    print(f"  Offset key changed:         {changes['offset_key_changed']}")
    print(f"  Segment changed:            {changes['segment_changed']}")
    print(f"  New in dual:                {changes['new_in_dual']}")
    print(f"  Missing in dual:            {changes['missing_in_dual']}")
    print(f"  Text changed (merged):      {changes['text_changed']}")
    print(f"{'='*100}")


def show_data_segment_growth(zh_blob, dual_blob):
    """Show how data segments grew for functions with merged strings."""
    zh_funcs = disassemble_all_functions(zh_blob)
    dual_funcs = disassemble_all_functions(dual_blob)
    
    print(f"\n{'='*100}")
    print("DATA SEGMENT SIZE COMPARISON")
    print(f"{'='*100}")
    
    for fid in sorted(set(zh_funcs.keys()) & set(dual_funcs.keys())):
        zh_func = zh_funcs[fid]
        dual_func = dual_funcs[fid]
        
        if zh_func['data_len'] != dual_func['data_len']:
            print(f"  func 0x{fid:04X}: zh_data_len={zh_func['data_len']} dual_data_len={dual_func['data_len']} "
                  f"delta={dual_func['data_len'] - zh_func['data_len']:+d}")
            
            # Show what strings were added
            zh_entries = extract_data_segment(zh_func['data_segment'])
            dual_entries = extract_data_segment(dual_func['data_segment'])
            
            # Find new strings in dual
            zh_strings = {off: text for off, typ, text in zh_entries if typ == 'str'}
            dual_strings = {off: text for off, typ, text in dual_entries if typ == 'str'}
            
            for off, text in dual_strings.items():
                if off not in zh_strings:
                    preview = text[:100] + ("..." if len(text) > 100 else "")
                    print(f"    NEW at 0x{off:04X}: {preview.encode('ascii', 'replace').decode()}")


def show_specific_example(zh_blob, dual_blob, func_id_hex):
    """Show detailed comparison for a specific function."""
    fid = int(func_id_hex, 16) if isinstance(func_id_hex, str) else func_id_hex
    zh_funcs = disassemble_all_functions(zh_blob)
    dual_funcs = disassemble_all_functions(dual_blob)
    
    zh_func = zh_funcs.get(fid)
    dual_func = dual_funcs.get(fid)
    
    if not zh_func:
        print(f"Function 0x{fid:04X} not found in zh")
        return
    if not dual_func:
        print(f"Function 0x{fid:04X} not found in dual")
        return
    
    print(f"\n{'='*100}")
    print(f"DETAILED COMPARISON: Function 0x{fid:04X}")
    print(f"{'='*100}")
    print(f"  zh:  data_len={zh_func['data_len']} code_len={len(zh_func['instructions'])}")
    print(f"  dual: data_len={dual_func['data_len']} code_len={len(dual_func['instructions'])}")
    
    # Show data segment strings
    print(f"\n  ZH DATA SEGMENT STRINGS:")
    for off, typ, val in extract_data_segment(zh_func['data_segment']):
        if typ == 'str':
            print(f"    0x{off:04X}: {val[:100]}")
    
    print(f"\n  DUAL DATA SEGMENT STRINGS:")
    for off, typ, val in extract_data_segment(dual_func['data_segment']):
        if typ == 'str':
            print(f"    0x{off:04X}: {val[:100]}")
    
    # Show say lines
    print(f"\n  ZH SAY LINES:")
    for l in analyze_function(zh_func, fid):
        print(f"    func={l['func_id']} offset_key={l['offset_key']} seg={l['segment']} addr={l['code_addr']}")
        print(f"      addsi={l['addsi_offsets']} text={l['text_preview']}")
    
    print(f"\n  DUAL SAY LINES:")
    for l in analyze_function(dual_func, fid):
        print(f"    func={l['func_id']} offset_key={l['offset_key']} seg={l['segment']} addr={l['code_addr']}")
        print(f"      addsi={l['addsi_offsets']} text={l['text_preview']}")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Verify usecode.dual offset changes")
    ap.add_argument("--zh", default="D:/project/Exult-for-zh/tools/voice_acting/_live/usecode.zh")
    ap.add_argument("--dual", default="D:/project/Exult-for-zh/tools/voice_acting/_live/usecode.dual")
    ap.add_argument("--review", default="D:/project/Exult-for-zh/tools/voice_acting/bilingual_mapping_review.json")
    ap.add_argument("--func", help="Specific function ID (hex) to analyze in detail")
    ap.add_argument("--full", action="store_true", help="Show full comparison (can be verbose)")
    args = ap.parse_args()
    
    zh_path = Path(args.zh)
    dual_path = Path(args.dual)
    review_path = Path(args.review) if args.review else None
    
    if not zh_path.exists():
        print(f"ERROR: {zh_path} not found")
        return 1
    if not dual_path.exists():
        print(f"ERROR: {dual_path} not found")
        return 1
    
    zh_blob = zh_path.read_bytes()
    dual_blob = dual_path.read_bytes()
    
    print(f"Loaded: {zh_path} ({len(zh_blob)} bytes)")
    print(f"Loaded: {dual_path} ({len(dual_blob)} bytes)")
    
    if args.func:
        show_specific_example(zh_blob, dual_blob, args.func)
    else:
        if args.full:
            compare_functions(zh_blob, dual_blob, review_path)
        show_data_segment_growth(zh_blob, dual_blob)


if __name__ == "__main__":
    main()