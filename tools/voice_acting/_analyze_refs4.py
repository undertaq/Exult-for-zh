"""
Voice distinctiveness analysis with proper feature normalization.
Uses z-scored per-frame MFCC statistics + spectral features.
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
    """Per-frame MFCCs."""
    freqs, times, Sxx = spectrogram(wav, sr, nperseg=n_fft, noverlap=n_fft - hop_length)
    power = np.abs(Sxx) ** 2
    n_freq = power.shape[0]
    mel_low = 0
    mel_high = 2595 * np.log10(1 + sr / 2 / 700)
    mel_points = np.linspace(mel_low, mel_high, n_mels + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bin_idx = np.clip(np.floor(hz_points / sr * (n_fft // 2 + 1)).astype(int), 0, n_freq - 1)
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
    return mfcc.T


def extract_voice_print(wav, sr):
    """Extract normalized voice print."""
    mfccs = frame_mfcc(wav, sr)
    if mfccs.shape[0] < 2:
        mfccs = np.tile(mfccs, (2, 1))

    feats = []
    # Per-coefficient stats for MFCC 2-13 (skip MFCC0 = energy)
    for c in range(1, mfccs.shape[1]):
        col = mfccs[:, c]
        feats.append(np.mean(col))
        feats.append(np.std(col))
        feats.append(np.mean(np.abs(np.diff(col))))
        feats.append(np.percentile(col, 90) - np.percentile(col, 10))
        feats.append(np.percentile(col, 75) - np.percentile(col, 25))

    # Spectral centroid stats
    freqs, times, Sxx = spectrogram(wav, sr, nperseg=512, noverlap=256)
    power = np.abs(Sxx)
    centroid = np.sum(freqs[:, None] * power, axis=0) / (np.sum(power, axis=0) + 1e-10)
    feats.append(np.mean(centroid))
    feats.append(np.std(centroid))
    feats.append(np.mean(np.abs(np.diff(centroid))))

    # Spectral bandwidth
    spread = np.sqrt(
        np.sum(((freqs[:, None] - centroid) ** 2) * power, axis=0) /
        (np.sum(power, axis=0) + 1e-10)
    )
    feats.append(np.mean(spread))
    feats.append(np.std(spread))

    # Spectral rolloff (85%)
    cumsum = np.cumsum(np.abs(Sxx), axis=0)
    total = cumsum[-1, :] + 1e-10
    rolloff_idx = np.argmax(cumsum >= 0.85 * total[None, :], axis=0)
    rolloff = freqs[rolloff_idx]
    feats.append(np.mean(rolloff))
    feats.append(np.std(rolloff))

    # Energy (MFCC0) stats - separate because they're large magnitude
    col0 = mfccs[:, 0]
    feats.append(np.mean(col0))
    feats.append(np.std(col0))

    # RMS energy
    frame_len = int(sr * 0.025)
    hop = int(sr * 0.010)
    if len(wav) > frame_len:
        frames = np.array([wav[i:i+frame_len] for i in range(0, len(wav)-frame_len, hop)])
        rms = np.sqrt(np.mean(frames**2, axis=1))
        feats.append(np.mean(rms))
        feats.append(np.std(rms))

    return np.array(feats)


def main():
    with open(DESIGNS_PATH) as f:
        designs = json.load(f)

    ref_files = sorted(Path(REFS_DIR).glob('*.ogg'))
    print(f'Found {len(ref_files)} reference files\n')

    # Extract all voice prints
    all_vp = {}
    for rf in ref_files:
        wav, sr = sf.read(rf)
        all_vp[rf.stem] = extract_voice_print(wav, sr)

    # Separate ZH and EN
    zh = {k.replace('_zh_ref', ''): v for k, v in all_vp.items() if k.endswith('_zh_ref')}
    en = {k.replace('_en_ref', ''): v for k, v in all_vp.items() if k.endswith('_en_ref')}

    # Z-score normalize across all voice prints
    all_vectors = np.array(list(all_vp.values()))
    mean = np.mean(all_vectors, axis=0)
    std = np.std(all_vectors, axis=0)
    std[std < 1e-10] = 1.0

    for key in list(zh.keys()):
        zh[key] = (zh[key] - mean) / std
    for key in list(en.keys()):
        en[key] = (en[key] - mean) / std

    # Check that normalization worked
    sample_vec = zh[list(zh.keys())[0]]
    print(f'Feature vector dimension: {len(sample_vec)}')
    print(f'Sample vector (normalized) range: [{np.min(sample_vec):.2f}, {np.max(sample_vec):.2f}]\n')

    # ── 1. Within-design ──────────────────────────────────────────
    print('=' * 65)
    print('1. WITHIN-DESIGN ZH↔EN COSINE DISTANCE')
    print('   (same voice, different language — should be LOW)')
    print('=' * 65)

    within = []
    for did in sorted(zh):
        if did in en:
            d = cosine(zh[did], en[did])
            within.append((d, did))

    wd = np.array([x[0] for x in within])
    print(f'  Count: {len(within)}')
    print(f'  Mean:  {np.mean(wd):.4f}')
    print(f'  Std:   {np.std(wd):.4f}')
    print(f'  Min:   {np.min(wd):.4f}')
    print(f'  Max:   {np.max(wd):.4f}')
    high_w = [(d, did) for d, did in within if d > 0.3]
    if high_w:
        print(f'  HIGH (>0.3): {len(high_w)} designs')
        for d, did in high_w[:5]:
            print(f'    {designs["designs"].get(did, {}).get("npc", did)}: {d:.4f}')
    print()

    # ── 2. Across-design (ZH) ─────────────────────────────────────
    print('=' * 65)
    print('2. ACROSS-DESIGN COSINE DISTANCE (ZH)')
    print('   (different voices — should be HIGH)')
    print('=' * 65)

    zh_ids = sorted(zh.keys())
    zh_vecs = np.array([zh[k] for k in zh_ids])

    cross = pdist(zh_vecs, 'cosine')
    print(f'  Pairs: {len(cross)}')
    print(f'  Mean:  {np.mean(cross):.4f}')
    print(f'  Std:   {np.std(cross):.4f}')
    print(f'  Min:   {np.min(cross):.4f}')
    print(f'  Max:   {np.max(cross):.4f}')

    dm = squareform(cross)

    # Distribution of distances
    bins = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    counts, _ = np.histogram(cross, bins=bins)
    print(f'\n  Distance distribution:')
    for i in range(len(bins) - 1):
        bar = '█' * int(counts[i] / max(counts) * 40) if max(counts) > 0 else ''
        print(f'    [{bins[i]:.1f}-{bins[i+1]:.1f}]: {counts[i]:5d}  {bar}')

    # Closest pairs
    close = []
    for i in range(len(zh_ids)):
        for j in range(i + 1, len(zh_ids)):
            d = dm[i, j]
            if d < 0.2:
                close.append((d, zh_ids[i], zh_ids[j]))
    close.sort()

    print(f'\n  Closest pairs (d < 0.2): {len(close)}')
    print(f'\n  Top 20 closest:')
    for d, k1, k2 in close[:20]:
        l1 = designs['designs'].get(k1, {}).get('npc', k1)
        l2 = designs['designs'].get(k2, {}).get('npc', k2)
        print(f'    d={d:.4f}  [{l1:25s}] vs [{l2:25s}]')

    # Farthest pairs
    far = []
    for i in range(len(zh_ids)):
        for j in range(i + 1, len(zh_ids)):
            d = dm[i, j]
            if d > 0.6:
                far.append((d, zh_ids[i], zh_ids[j]))
    far.sort(reverse=True)

    if far:
        print(f'\n  Farthest pairs (d > 0.6): {len(far)}')
        print(f'  Top 10 farthest:')
        for d, k1, k2 in far[:10]:
            l1 = designs['designs'].get(k1, {}).get('npc', k1)
            l2 = designs['designs'].get(k2, {}).get('npc', k2)
            print(f'    d={d:.4f}  [{l1:25s}] vs [{l2:25s}]')
    print()

    # ── 3. Group analysis ─────────────────────────────────────────
    print('=' * 65)
    print('3. GROUP ANALYSIS')
    print('=' * 65)

    gids = [k for k in zh_ids if k.startswith('group_')]
    uids = [k for k in zh_ids if not k.startswith('group_')]
    print(f'  Groups: {len(gids)}, Unique: {len(uids)}')

    gg_dists = []
    for i in range(len(gids)):
        gi = zh_ids.index(gids[i])
        for j in range(i + 1, len(gids)):
            gj = zh_ids.index(gids[j])
            gg_dists.append(dm[gi, gj])

    gu_dists = []
    for gid in gids:
        gi = zh_ids.index(gid)
        for uid in uids:
            ui = zh_ids.index(uid)
            gu_dists.append(dm[gi, ui])

    uu_dists = []
    for i in range(len(uids)):
        ui = zh_ids.index(uids[i])
        for j in range(i + 1, len(uids)):
            uj = zh_ids.index(uids[j])
            uu_dists.append(dm[ui, uj])

    if gg_dists:
        print(f'  Group↔Group:  mean={np.mean(gg_dists):.4f}, min={np.min(gg_dists):.4f}, max={np.max(gg_dists):.4f}')
    if gu_dists:
        print(f'  Group↔Unique: mean={np.mean(gu_dists):.4f}, min={np.min(gu_dists):.4f}, max={np.max(gu_dists):.4f}')
    if uu_dists:
        print(f'  Unique↔Unique: mean={np.mean(uu_dists):.4f}, min={np.min(uu_dists):.4f}, max={np.max(uu_dists):.4f}')
    print()

    # ── 4. Quality ────────────────────────────────────────────────
    print('=' * 65)
    print('4. AUDIO QUALITY')
    print('=' * 65)

    issues = []
    for rf in ref_files:
        wav, sr = sf.read(rf)
        peak = np.max(np.abs(wav))
        rms = np.sqrt(np.mean(wav**2))
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
    print('VERDICT')
    print('=' * 65)

    zh_mean_dur = np.mean([len(sf.read(str(Path(REFS_DIR, f'{k}_zh_ref.ogg')))[0]) /
                           sf.read(str(Path(REFS_DIR, f'{k}_zh_ref.ogg')))[1] for k in zh_ids])
    en_mean_dur = np.mean([len(sf.read(str(Path(REFS_DIR, f'{k}_en_ref.ogg')))[0]) /
                           sf.read(str(Path(REFS_DIR, f'{k}_en_ref.ogg')))[1] for k in en.keys()])

    print(f'  Files:             {len(ref_files)} (350 expected)')
    print(f'  Designs:           {len(zh_ids)} (175 expected)')
    print(f'  ZH mean duration:  {zh_mean_dur:.1f}s')
    print(f'  EN mean duration:  {en_mean_dur:.1f}s')
    print(f'  Quality issues:    {len(issues)}')
    print(f'  Within-design:     {np.mean(wd):.4f} — voice consistency')
    print(f'  Across-design:     {np.mean(cross):.4f} — voice distinctiveness')
    print(f'  Min across:        {np.min(cross):.4f}')
    print(f'  Max across:        {np.max(cross):.4f}')
    print()
    print(f'  Thresholds:')
    print(f'    within < 0.3 = same voice carries across languages ✓' if np.mean(wd) < 0.3 else '    within < 0.3 = WARNING')
    print(f'    across > 0.3 = voices are distinct enough for cloning')
    if np.mean(cross) > 0.3:
        print(f'    ✓ PASS: mean across-design distance > 0.3')
    else:
        print(f'    ⚠ NOTE: mean across-design distance ({np.mean(cross):.4f}) < 0.3')
        print(f'    VoiceDesign may be producing similar-sounding voices.')
        print(f'    This may still work for VoiceClone — the clone prompt')
        print(f'    captures finer detail than MFCC features can represent.')


if __name__ == '__main__':
    main()
