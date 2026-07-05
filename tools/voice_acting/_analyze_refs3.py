"""
Proper voice distinctiveness analysis using frame-level MFCC statistics.
Different-length audio is handled via per-frame stats (mean/std/skew per coefficient).
"""
import json
import os
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import spectrogram
from scipy.fft import dct
from scipy.spatial.distance import pdist, squareform, cosine

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REFS_DIR = os.path.join(SCRIPT_DIR, 'refs')
DESIGNS_PATH = os.path.join(SCRIPT_DIR, 'npc_voice_designs.json')


def frame_mfcc(wav, sr, n_mfcc=13, n_fft=512, hop_length=256, n_mels=26):
    """Compute per-frame MFCCs."""
    # Power spectrogram
    freqs, times, Sxx = spectrogram(wav, sr, nperseg=n_fft, noverlap=n_fft - hop_length)
    power = np.abs(Sxx) ** 2
    n_freq = power.shape[0]

    # Mel filterbank
    mel_low = 0
    mel_high = 2595 * np.log10(1 + sr / 2 / 700)
    mel_points = np.linspace(mel_low, mel_high, n_mels + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bin_idx = np.clip(
        np.floor(hz_points / sr * (n_fft // 2 + 1)).astype(int),
        0, n_freq - 1
    )

    n_frames = power.shape[1]
    fbank = np.zeros((n_mels, n_frames))
    for i in range(n_mels):
        start = bin_idx[i]
        mid = bin_idx[i + 1]
        end = bin_idx[i + 2]
        for t in range(n_frames):
            for b in range(start, mid):
                if mid > start:
                    fbank[i, t] += power[b, t] * (b - start) / (mid - start)
            for b in range(mid, end):
                if end > mid:
                    fbank[i, t] += power[b, t] * (end - b) / (end - mid)

    fbank = np.where(fbank > 0, np.log(fbank + 1e-10), 0)
    mfcc = dct(fbank, axis=0, type=2, norm='ortho')[:n_mfcc]
    return mfcc.T  # (n_frames, n_mfcc)


def extract_voice_print(wav, sr):
    """
    Extract a duration-invariant voice print from audio.
    Returns a feature vector based on frame-level MFCC statistics.
    """
    if len(wav) < sr * 0.05:
        return np.zeros(13 * 4 + 4)

    mfccs = frame_mfcc(wav, sr)
    if mfccs.shape[0] < 2:
        mfccs = np.tile(mfccs, (2, 1))

    feats = []
    # Per-coefficient statistics (duration-invariant)
    for c in range(mfccs.shape[1]):
        col = mfccs[:, c]
        feats.append(np.mean(col))
        feats.append(np.std(col))
        feats.append(np.mean(np.abs(np.diff(col))))  # temporal variation
        feats.append(np.percentile(col, 90) - np.percentile(col, 10))  # range

    # Global features
    # Pitch proxy: mean of MFCC0 (energy)
    # Spectral tilt: MFCC1 slope
    # Jitter-like: std of MFCC0 delta
    # Also add spectral centroid statistics
    freqs, times, Sxx = spectrogram(wav, sr, nperseg=512, noverlap=256)
    power = np.abs(Sxx)
    centroid = np.sum(freqs[:, None] * power, axis=0) / (np.sum(power, axis=0) + 1e-10)
    feats.append(np.mean(centroid))
    feats.append(np.std(centroid))
    feats.append(np.mean(np.abs(np.diff(centroid))))

    # RMS energy stats
    frame_len = int(sr * 0.025)
    hop = int(sr * 0.010)
    if len(wav) > frame_len:
        frames = np.array([
            wav[i:i + frame_len]
            for i in range(0, len(wav) - frame_len, hop)
        ])
        rms = np.sqrt(np.mean(frames ** 2, axis=1))
        feats.append(np.mean(rms))
        feats.append(np.std(rms))
    else:
        feats.append(0.0)
        feats.append(0.0)

    return np.array(feats)


def main():
    with open(DESIGNS_PATH, 'r', encoding='utf-8') as f:
        designs = json.load(f)

    ref_files = sorted(Path(REFS_DIR).glob('*.ogg'))
    print(f'Found {len(ref_files)} reference files')

    # Extract voice prints
    voice_prints = {}
    for rf in ref_files:
        wav, sr = sf.read(rf)
        vp = extract_voice_print(wav, sr)
        voice_prints[rf.stem] = vp

    # Group by design
    design_zh = {}
    design_en = {}
    for stem, vp in voice_prints.items():
        if stem.endswith('_zh_ref'):
            did = stem[:-7]
            design_zh[did] = vp
        elif stem.endswith('_en_ref'):
            did = stem[:-7]
            design_en[did] = vp

    print(f'Voice prints extracted for {len(design_zh)} ZH + {len(design_en)} EN designs\n')

    # ── 1. Within-design ZH vs EN ────────────────────────────────
    print('=' * 65)
    print('1. WITHIN-DESIGN ZH↔EN COSINE DISTANCE')
    print('   (should be LOW — same voice, different language)')
    print('=' * 65)

    within = []
    for did in sorted(design_zh):
        if did in design_en:
            d = cosine(design_zh[did], design_en[did])
            within.append((d, did))

    wd = np.array([x[0] for x in within])
    print(f'  Mean:  {np.mean(wd):.4f}')
    print(f'  Min:   {np.min(wd):.4f}')
    print(f'  Max:   {np.max(wd):.4f}')
    print(f'  Std:   {np.std(wd):.4f}')
    high_within = [(d, did) for d, did in within if d > 0.15]
    if high_within:
        print(f'  HIGH (>0.15): {len(high_within)} designs')
        for d, did in high_within[:5]:
            label = designs['designs'].get(did, {}).get('npc', did)
            print(f'    {label}: {d:.4f}')
    print()

    # ── 2. Across-design (ZH only) ───────────────────────────────
    print('=' * 65)
    print('2. ACROSS-DESIGN COSINE DISTANCE (ZH)')
    print('   (should be HIGH — different voices)')
    print('=' * 65)

    zh_ids = sorted(design_zh.keys())
    zh_vecs = np.array([design_zh[k] for k in zh_ids])

    cross = pdist(zh_vecs, 'cosine')
    print(f'  Pairs: {len(cross)}')
    print(f'  Mean:  {np.mean(cross):.4f}')
    print(f'  Min:   {np.min(cross):.4f}')
    print(f'  Max:   {np.max(cross):.4f}')
    print(f'  Std:   {np.std(cross):.4f}')

    dm = squareform(cross)
    
    # Find closest pairs
    close = []
    for i in range(len(zh_ids)):
        for j in range(i + 1, len(zh_ids)):
            c = dm[i, j]
            if c < 0.05:
                close.append((c, zh_ids[i], zh_ids[j]))
    close.sort()
    print(f'\n  Pairs with distance < 0.05: {len(close)}')
    print(f'\n  Top 30 closest pairs:')
    for c, k1, k2 in close[:30]:
        l1 = designs['designs'].get(k1, {}).get('npc', k1)
        l2 = designs['designs'].get(k2, {}).get('npc', k2)
        print(f'    d={c:.4f}  [{l1:25s}] vs [{l2:25s}]')
    
    # Far pairs
    far = [(dm[i, j], zh_ids[i], zh_ids[j])
           for i in range(len(zh_ids)) for j in range(i + 1, len(zh_ids))
           if dm[i, j] > 0.15]
    far.sort(reverse=True)
    if far:
        print(f'\n  Top 10 farthest pairs (d > 0.15):')
        for c, k1, k2 in far[:10]:
            l1 = designs['designs'].get(k1, {}).get('npc', k1)
            l2 = designs['designs'].get(k2, {}).get('npc', k2)
            print(f'    d={c:.4f}  [{l1:25s}] vs [{l2:25s}]')
    print()

    # ── 3. Group analysis ────────────────────────────────────────
    print('=' * 65)
    print('3. GROUP ANALYSIS')
    print('=' * 65)

    gids = [k for k in zh_ids if k.startswith('group_')]
    uids = [k for k in zh_ids if not k.startswith('group_')]
    print(f'  Groups: {len(gids)}, Unique: {len(uids)}')

    # Group↔Group
    gg = []
    for i in range(len(gids)):
        gi = zh_ids.index(gids[i])
        for j in range(i + 1, len(gids)):
            gj = zh_ids.index(gids[j])
            gg.append(dm[gi, gj])
    if gg:
        print(f'  Group↔Group mean: {np.mean(gg):.4f}, min: {np.min(gg):.4f}')

    # Group↔Unique
    gu = []
    for gid in gids:
        gi = zh_ids.index(gid)
        for uid in uids:
            ui = zh_ids.index(uid)
            gu.append(dm[gi, ui])
    if gu:
        print(f'  Group↔Unique mean: {np.mean(gu):.4f}, min: {np.min(gu):.4f}')

    # Unique↔Unique
    uu = []
    for i in range(len(uids)):
        ui = zh_ids.index(uids[i])
        for j in range(i + 1, len(uids)):
            uj = zh_ids.index(uids[j])
            uu.append(dm[ui, uj])
    if uu:
        print(f'  Unique↔Unique mean: {np.mean(uu):.4f}, min: {np.min(uu):.4f}')
    print()

    # ── 4. Quality checks ─────────────────────────────────────────
    print('=' * 65)
    print('4. AUDIO QUALITY')
    print('=' * 65)

    issues = []
    for rf in ref_files:
        wav, sr = sf.read(rf)
        peak = np.max(np.abs(wav))
        rms = np.sqrt(np.mean(wav ** 2))
        dc = np.mean(wav)
        dur = len(wav) / sr
        if peak > 0.99:
            issues.append(f'  CLIPPING:  {rf.name} (peak={peak:.3f})')
        if rms < 0.0001 and dur > 0.5:
            issues.append(f'  SILENCE:   {rf.name}')
        if abs(dc) > 0.05:
            issues.append(f'  DC OFFSET: {rf.name} (dc={dc:.4f})')
        if dur < 1.0:
            issues.append(f'  TOO SHORT: {rf.name} ({dur:.1f}s)')

    if issues:
        for i in issues:
            print(i)
    else:
        print('  No quality issues found.')
    print()

    # ── Summary ──────────────────────────────────────────────────
    print('=' * 65)
    print('SUMMARY')
    print('=' * 65)
    print(f'  Total files:             {len(ref_files)}')
    print(f'  Designs:                 {len(zh_ids)}')
    zh_durs = [len(sf.read(rf)[0]) / sf.read(rf)[1] for rf in sorted(Path(REFS_DIR).glob('*_zh_ref.ogg'))]
    en_durs = [len(sf.read(rf)[0]) / sf.read(rf)[1] for rf in sorted(Path(REFS_DIR).glob('*_en_ref.ogg'))]
    print(f'  Duration:                ZH mean {np.mean(zh_durs):.1f}s, EN mean {np.mean(en_durs):.1f}s')
    print(f'  Within-design distance:   {np.mean(wd):.4f} (expect < 0.15 ✓)' if np.mean(wd) < 0.15 else f'  Within-design distance:   {np.mean(wd):.4f} (WARNING: high!)')
    print(f'  Across-design distance:   {np.mean(cross):.4f} (expect > 0.05)' + (' ✓' if np.mean(cross) > 0.05 else ' ✗'))
    print(f'  Closest pair distance:    {np.min(cross):.4f}')
    print(f'  Quality issues:          {len(issues)}')


if __name__ == '__main__':
    main()
