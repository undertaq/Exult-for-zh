#!/usr/bin/env python3
"""Background review HTML updater — runs independently of generator processes."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_voice_review_html import rows_from_full_voice, write_report

VOICE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent / 'voice'
MAPPING_PATH = Path(os.path.dirname(os.path.abspath(__file__))) / 'bilingual_mapping_review.json'
RUN_START_TIME = 1784618900  # Start of generation run (~15:28)
OUT_DIR_NEW = Path(os.path.dirname(os.path.abspath(__file__))) / 'voice_review_new'
OUT_DIR = VOICE_DIR / 'review_samples' / 'full_generated_review'

interval = 20

print(f"Review HTML updater started (interval={interval}s)")
print(f"  Voice dir: {VOICE_DIR}")
print(f"  Mapping:   {MAPPING_PATH}")
print(f"  Output (New):  {OUT_DIR_NEW / 'index.html'}")
print(f"  Output (Full): {OUT_DIR / 'index.html'}")
sys.stdout.flush()

last_update = 0
while True:
    now = time.time()
    if last_update and now - last_update < interval:
        time.sleep(5)
        continue

    try:
        # Write NEW-ONLY review report
        rows_new = rows_from_full_voice(VOICE_DIR, MAPPING_PATH, since_mtime=RUN_START_TIME, only_new=True)
        write_report(
            rows_new, OUT_DIR_NEW,
            'Newly Generated Voice Review (Current Run)',
            review_id=str(RUN_START_TIME),
        )

        # Write FULL review report
        rows_all = rows_from_full_voice(VOICE_DIR, MAPPING_PATH)
        write_report(
            rows_all, OUT_DIR,
            'Generated Voice Review - All Files',
            review_id='all',
        )

        elapsed = time.time() - now
        print(
            f"[{time.strftime('%H:%M:%S')}] "
            f"Updated Review HTML: {len(rows_new)} NEW rows in voice_review_new/index.html, "
            f"{len(rows_all)} total rows in full_generated_review/index.html ({elapsed:.1f}s)"
        )
        sys.stdout.flush()
        last_update = now
    except Exception as ex:
        print(f"[{time.strftime('%H:%M:%S')}] Review update error: {ex}")
        sys.stdout.flush()
        time.sleep(15)

