"""
Deep analysis: check if voices are truly distinct.
Uses proper MFCCs (13 coefficients) + spectral contrast features.
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import spectrogram
from scipy.fft import dct
from scipy.spatial.distance import cosine, pdist, squareform

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
REFS_DIR = os.path.join(PROJECT_DIR, 'voice', 'refs')
DESIGNS_PATH = os.path.join(SCRIPT_DIR, 'npc_voice_designs.json')


def extract_mfcc(wav, sr, n_mfcc=13, n_fft=512, hop_length=256, n_mels=26):
    """Extract MFCC features from audio."""
    # Compute spectrogram
    freqs, times, Sxx = spectrogram(wav, sr, nperseg=n_fft, noverlap=n_fft - hop_length)
    power = np.abs(Sxx) ** 2

    # Create mel filterbank
    mel_low = 0
    mel_high = 2595 * np.log10(1 + sr / 2 / 700)
    mel_points = np.linspace(mel_low, mel_high, n_mels + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bin_points = np.floor(hz_points / sr * (n_fft // 2 + 1)).astype(int)
    bin_points = np.clip(bin_points, 0, power.shape[0] - 1)

    fbank = np.zeros((n_mels, power.shape[1]))
    for i in range(n_mels):
        start = bin_points[i]
        mid = bin_points[i + 1]
        end = bin_points[i + 2]
        for t in range(power.shape[1]):
            # Triangular filter
            for b in range(start, mid):
                if mid > start:
                    fbank[i, t] += power[b, t] * (b - start) / (mid - start)
            for b in range(mid, end):
                if end > mid:
                    fbank[i, t] += power[b, t] * (end - b) / (end - mid)

    fbank = np.where(fbank > 0, np.log(fbank + 1e-10), 0)
    mfcc = dct(fbank, axis=0, type=2, norm='ortho')[:n_mfcc]
    return mfcc


def extract_features_deep(wav, sr):
    """Full feature set for voice comparison."""
    feats = {}

    # Duration-normalized
    feats['duration'] = len(wav) / sr

    # RMS energy envelope (mean + std)
    frame_len = int(sr * 0.025)  # 25ms frames
    hop = int(sr * 0.010)  # 10ms hop
    if len(wav) > frame_len:
        frames = np.array([
            wav[i:i + frame_len]
            for i in range(0, len(wav) - frame_len, hop)
        ])
        rms = np.sqrt(np.mean(frames ** 2, axis=1))
        feats['rms_mean'] = float(np.mean(rms))
        feats['rms_std'] = float(np.std(rms))
    else:
        feats['rms_mean'] = float(np.sqrt(np.mean(wav ** 2)))
        feats['rms_std'] = 0.0

    # ZCR statistics
    zcr_frames = np.array([
        np.mean(np.abs(np.diff(np.sign(f)))) / 2
        for f in frames
    ]) if len(wav) > frame_len else np.array([0])
    feats['zcr_mean'] = float(np.mean(zcr_frames))
    feats['zcr_std'] = float(np.std(zcr_frames))

    # MFCCs (13 coefficients, averaged over time)
    mfcc = extract_mfcc(wav, sr)
    for i in range(min(13, mfcc.shape[0])):
        feats[f'mfcc{i + 1}_mean'] = float(np.mean(mfcc[i]))
        feats[f'mfcc{i + 1}_std'] = float(np.std(mfcc[i]))

    # Spectral centroid
    freqs, times, Sxx = spectrogram(wav, sr, nperseg=512, noverlap=256)
    power = np.abs(Sxx)
    centroid = np.sum(freqs[:, None] * power, axis=0) / (np.sum(power, axis=0) + 1e-10)
    feats['centroid_mean'] = float(np.mean(centroid))
    feats['centroid_std'] = float(np.std(centroid))

    # Spectral rolloff (frequency below which 85% energy)
    cumsum = np.cumsum(power, axis=0)
    total = cumsum[-1, :] + 1e-10
    rolloff_idx = np.argmax(cumsum >= 0.85 * total[None, :], axis=0)
    rolloff = freqs[rolloff_idx]
    feats['rolloff_mean'] = float(np.mean(rolloff))

    return feats


def feats_to_vector(feats):
    """Convert feature dict to vector, excluding duration."""
    keys = sorted([k for k in feats if k != 'duration'])
    return np.array([feats[k] for k in keys])


def main():
    with open(DESIGNS_PATH, 'r', encoding='utf-8') as f:
        designs = json.load(f)

    ref_files = sorted(Path(REFS_DIR).glob('*.ogg'))
    print(f'Found {len(ref_files)} ref files')

    # ── 1. Extract features ──────────────────────────────────────
    all_features = {}
    for rf in ref_files:
        try:
            wav, sr = sf.read(rf)
            feats = extract_features_deep(wav, sr)
            all_features[rf.stem] = feats
        except Exception as e:
            print(f'ERROR {rf.name}: {e}')

    # Group by design
    design_zh = {}
    design_en = {}
    for stem, feats in all_features.items():
        if '_zh_ref' in stem:
            did = stem.replace('_zh_ref', '')
            design_zh[did] = feats
        elif '_en_ref' in stem:
            did = stem.replace('_en_ref', '')
            design_en[did] = feats

    design_ids = sorted(set(list(design_zh.keys()) + list(design_en.keys())))
    print(f'Features extracted for {len(design_zh)} ZH + {len(design_en)} EN designs')

    # ── 2. Within-design ZH vs EN ────────────────────────────────
    print('\n' + '=' * 65)
    print('WITHIN-DESIGN ZH vs EN (same voice, different language)')
    print('=' * 65)

    within_dists = []
    for did in design_ids:
        if did in design_zh and did in design_en:
            v_zh = feats_to_vector(design_zh[did])
            v_en = feats_to_vector(design_en[did])
            d = cosine(v_zh, v_en)
            within_dists.append((d, did))

    within_dists.sort()
    wd = np.array([x[0] for x in within_dists])
    print(f'  Count: {len(within_dists)}')
    print(f'  Mean:  {np.mean(wd):.4f}')
    print(f'  Std:   {np.std(wd):.4f}')
    print(f'  Min:   {np.min(wd):.4f}')
    print(f'  Max:   {np.max(wd):.4f}')
    high = [x for x in within_dists if x[0] > 0.2]
    if high:
        print(f'  HIGH (>0.2): {len(high)}')
        for d, did in high[:10]:
            label = designs['designs'].get(did, {}).get('npc', did)
            print(f'    {label}: {d:.4f}')

    # ── 3. Across-design distances ───────────────────────────────
    print('\n' + '=' * 65)
    print('ACROSS-DESIGN DISTANCES (should be HIGH — different voices)')
    print('=' * 65)

    # Use ZH features for cross-design comparison
    zh_keys = sorted(design_zh.keys())
    zh_vecs = np.array([feats_to_vector(design_zh[k]) for k in zh_keys])
    print(f'  Comparing {len(zh_keys)} designs using ZH features')

    cross_dists = pdist(zh_vecs, 'cosine')
    print(f'  Total pairs: {len(cross_dists)}')
    print(f'  Mean:  {np.mean(cross_dists):.4f}')
    print(f'  Std:   {np.std(cross_dists):.4f}')
    print(f'  Min:   {np.min(cross_dists):.4f}')
    print(f'  Max:   {np.max(cross_dists):.4f}')

    # Find most similar pairs
    dist_matrix = squareform(cross_dists)
    min_dist = np.min(cross_dists)
    print(f'\n  Minimum across-design distance: {min_dist:.4f}')
    print(f'  Threshold recommendation: min_dist should be > 0.05 for good distinctiveness')
    similar_threshold = 0.05
    n_similar = np.sum(cross_dists < similar_threshold)
    print(f'  Pairs with distance < {similar_threshold}: {n_similar}')

    # List all pairs with distance < 0.1
    threshold = 0.1
    close_pairs = []
    for i in range(len(zh_keys)):
        for j in range(i + 1, len(zh_keys)):
            d = dist_matrix[i, j]
            if d < threshold:
                close_pairs.append((d, zh_keys[i], zh_keys[j]))
    close_pairs.sort()

    print(f'\n  Pairs with distance < {threshold}:')
    for d, k1, k2 in close_pairs[:30]:
        d1 = designs['designs'].get(k1, {})
        d2 = designs['designs'].get(k2, {})
        l1 = d1.get('npc', k1)
        l2 = d2.get('npc', k2)
        print(f'    d={d:.4f}  [{l1:25s}] vs [{l2:25s}]')

    # ── 4. Group-level analysis ──────────────────────────────────
    print('\n' + '=' * 65)
    print('GROUP ANALYSIS')
    print('=' * 65)

    group_ids = [did for did in zh_keys if did.startswith('group_')]
    unique_ids = [did for did in zh_keys if not did.startswith('group_')]
    print(f'  Groups: {len(group_ids)}, Unique: {len(unique_ids)}')

    # Within-group pair distances
    for gid in group_ids:
        pass  # Only one vector per group currently

    # Between groups
    group_indices = [zh_keys.index(g) for g in group_ids if g in zh_keys]
    if len(group_indices) >= 2:
        g_dists = []
        for i in range(len(group_indices)):
            for j in range(i + 1, len(group_indices)):
                g_dists.append(dist_matrix[group_indices[i], group_indices[j]])
        print(f'  Group↔Group mean dist: {np.mean(g_dists):.4f}')

    # Closest group to any unique
    min_group_unique = float('inf')
    for gid in group_ids:
        gi = zh_keys.index(gid)
        for uid in unique_ids:
            ui = zh_keys.index(uid)
            d = dist_matrix[gi, ui]
            if d < min_group_unique:
                min_group_unique = d
    print(f'  Min Group↔Unique dist: {min_group_unique:.4f}')

    # ── 5. Identify potential voice cloning issues ───────────────
    print('\n' + '=' * 65)
    print('CLONE QUALITY CHECK')
    print('=' * 65)

    for rf in ref_files:
        try:
            wav, sr = sf.read(rf)
            # Check for clipping
            peak = np.max(np.abs(wav))
            dur = len(wav) / sr
            # Check for silence
            rms = np.sqrt(np.mean(wav ** 2))
            # Check for DC offset
            dc = np.mean(wav)
            if peak > 0.99:
                print(f'  CLIPPING: {rf.name} (peak={peak:.3f})')
            if rms < 0.001 and dur > 0.5:
                print(f'  SILENCE:  {rf.name} (rms={rms:.6f})')
            if abs(dc) > 0.05:
                print(f'  DC OFFSET: {rf.name} (dc={dc:.4f})')
        except Exception as e:
            pass

    # ── Summary ────────────────────────────────────────────────
    print('\n' + '=' * 65)
    print('SUMMARY')
    print('=' * 65)
    print(f'  Total ref files:          {len(ref_files)}')
    print(f'  Designs analyzed:         {len(zh_keys)} ZH + {len(design_en)} EN')
    print(f'  Within-design distance:    {np.mean(wd):.4f} (expect < 0.15)')
    print(f'  Across-design distance:    {np.mean(cross_dists):.4f} (expect >> 0.05)')
    print(f'  Pairs with d<0.05:        {n_similar}')


if __name__ == '__main__':
    main()
