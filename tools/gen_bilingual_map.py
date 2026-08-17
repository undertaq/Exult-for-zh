#!/usr/bin/env python3
"""
Generate bilingual_map.dat by analyzing English and Chinese usecode files.

This tool parses both usecode binaries, extracts conversation function
metadata, and builds a mapping table that translates Chinese usecode
offsets to English usecode offsets for voice file lookup.

Usage: python gen_bilingual_map.py <english_usecode> <chinese_usecode> <output_file>
"""

import struct
import sys
from pathlib import Path


BLMP_MAGIC = b'BLMP'


def read_usecode_functions(filepath):
    """Parse a usecode binary and extract function information.
    
    Usecode format:
    - 4 bytes: magic number 
    - Then function blocks, each with:
        - 4 bytes: function count in this block
        - Per function: id (4 bytes) + data
    
    Returns: dict[int, list[str]] — function_id -> list of string constants
    """
    data = Path(filepath).read_bytes()
    functions = {}
    
    pos = 4  # Skip magic
    while pos < len(data) - 8:
        # Read function count for this block
        count = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        
        if count == 0:
            continue
            
        # Read each function in this block
        for _ in range(count):
            if pos + 4 > len(data):
                break
            
            func_id = struct.unpack_from('<I', data, pos)[0]
            pos += 4
            
            # Try to extract string-like data near this function
            # Conversation strings are typically near the function start
            strings = []
            search_start = pos
            search_end = min(pos + 4096, len(data) - 1)
            
            i = search_start
            while i < search_end:
                byte = data[i]
                # Check for ASCII or UTF-8 string
                if 0x20 <= byte < 0x7f or byte >= 0x80:
                    str_start = i
                    # Collect string bytes
                    while i < search_end and (0x20 <= data[i] < 0x7f or data[i] >= 0x80):
                        i += 1
                    s = data[str_start:i].decode('utf-8', errors='ignore')
                    # Filter to reasonable conversation-like strings
                    if len(s) >= 5 and any(c in s for c in ' .,!?~'):
                        strings.append(s)
                else:
                    i += 1
            
            # Skip to next function (estimate function size)
            # Usecode functions vary in size; we use a heuristic
            # Actually, let's just track the function ID and its offset
            functions[func_id] = strings
    
    return functions


def build_mapping(en_functions, zh_functions):
    """Build mapping between Chinese and English function offsets.
    
    For each function that exists in both:
    - Match strings by position in their respective string lists
    - Create entries mapping zh function_id + string_index to en function_id + string_index
    
    Returns: list of dict entries
    """
    mappings = []
    
    common_funcs = set(en_functions.keys()) & set(zh_functions.keys())
    
    for func_id in sorted(common_funcs):
        en_strings = en_functions[func_id]
        zh_strings = zh_functions[func_id]
        
        min_count = min(len(en_strings), len(zh_strings))
        for i in range(min_count):
            # Use the segment index as the offset key
            mappings.append({
                'zh_func_id': func_id,
                'zh_offset_key': f'{i:x}',
                'segment': 0,
                'en_func_id': func_id,
                'en_offset_key': f'{i:x}',
            })
    
    return mappings


def write_bilingual_map(mappings, output_path):
    """Write bilingual_map.dat in BLMP format.
    
    Format:
    - BLMP magic (4 bytes)
    - entry_count (4 bytes uint32 LE)
    - For each entry:
        - zh_func_id (4 bytes int32 LE)
        - zh_offset_key (null-terminated string)
        - segment (2 bytes uint16 LE)
        - en_func_id (4 bytes int32 LE)
        - en_offset_key (null-terminated string)
    """
    with open(output_path, 'wb') as f:
        # Magic
        f.write(BLMP_MAGIC)
        
        # Entry count
        f.write(struct.pack('<I', len(mappings)))
        
        # Write each mapping
        for m in mappings:
            f.write(struct.pack('<i', m['zh_func_id']))
            f.write(m['zh_offset_key'].encode('utf-8') + b'\0')
            f.write(struct.pack('<H', m['segment']))
            f.write(struct.pack('<i', m['en_func_id']))
            f.write(m['en_offset_key'].encode('utf-8') + b'\0')


def verify_mapping(mappings):
    """Basic sanity check on the generated mapping."""
    if not mappings:
        print("WARNING: No mappings generated!")
        return
    
    # Check for duplicate entries
    seen = set()
    for m in mappings:
        key = (m['zh_func_id'], m['zh_offset_key'])
        if key in seen:
            print(f"WARNING: Duplicate mapping for func {m['zh_func_id']}, offset {m['zh_offset_key']}")
        seen.add(key)
    
    print(f"  Unique entries: {len(seen)}")


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <english_usecode> <chinese_usecode> <output_file>")
        print()
        print("  english_usecode:  Path to English usecode file (e.g. STATIC/usecode)")
        print("  chinese_usecode:  Path to Chinese usecode file (e.g. patch/usecode.zh)")
        print("  output_file:      Path for generated bilingual_map.dat")
        sys.exit(1)
    
    en_path = Path(sys.argv[1])
    zh_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])
    
    # Validate inputs
    if not en_path.exists():
        print(f"ERROR: English usecode not found: {en_path}")
        sys.exit(1)
    if not zh_path.exists():
        print(f"ERROR: Chinese usecode not found: {zh_path}")
        sys.exit(1)
    
    print(f"Using Python to parse usecode files...")
    print(f"  English: {en_path} ({en_path.stat().st_size} bytes)")
    print(f"  Chinese: {zh_path} ({zh_path.stat().st_size} bytes)")
    
    # Parse both usecode files
    print("\nParsing English usecode...")
    en_functions = read_usecode_functions(str(en_path))
    print(f"  Found {len(en_functions)} functions")
    
    print("\nParsing Chinese usecode...")
    zh_functions = read_usecode_functions(str(zh_path))
    print(f"  Found {len(zh_functions)} functions")
    
    # Build mapping
    print("\nBuilding voice mapping...")
    mappings = build_mapping(en_functions, zh_functions)
    print(f"  Generated {len(mappings)} voice mappings")
    
    # Verify mapping
    print("\nVerifying mapping...")
    verify_mapping(mappings)
    
    # Write output
    print(f"\nWriting bilingual map to: {output_path}")
    write_bilingual_map(mappings, str(output_path))
    
    output_size = output_path.stat().st_size if output_path.exists() else 0
    print(f"  Written {output_size} bytes")
    
    print("\nDone!")


if __name__ == '__main__':
    main()
