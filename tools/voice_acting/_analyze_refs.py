"""
Analyze reference voice clips for quality and distinctiveness.
Checks durations, spectral features, and inter-design distance.
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.spatial.distance import cosine

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
REFS_DIR = os.path.join(PROJECT_DIR, 'voice', 'refs')
DESIGNS_PATH = os.path.join(SCRIPT_DIR, 'npc_voice_designs.json')

SR_TARGET = 12000  # 12kHz per Qwen3-TTS spec


# ── Feature extraction ──────────────────────────────────────────────

def extract_features(wav, sr):
    """Extract a feature vector for voice comparison."""
    features = {}
    # Duration
    features['duration_s'] = len(wav) / sr
    # RMS energy
    features['rms'] = float(np.sqrt(np.mean(wav ** 2)))
    # Peak amplitude
    features['peak'] = float(np.max(np.abs(wav)))
    # Zero-crossing rate
    zcr = np.mean(np.abs(np.diff(np.sign(wav)))) / 2
    features['zcr'] = float(zcr)
    # Spectral centroid
    if len(wav) > 512:
        freqs, times, Sxx = signal.spectrogram(wav, sr, nperseg=512, noverlap=256)
        power = np.abs(Sxx)
        centroid = np.sum(freqs[:, None] * power, axis=0) / (np.sum(power, axis=0) + 1e-10)
        features['spectral_centroid_mean'] = float(np.mean(centroid))
        features['spectral_centroid_std'] = float(np.std(centroid))
        # Spectral bandwidth
        spread = np.sqrt(
            np.sum(((freqs[:, None] - centroid) ** 2) * power, axis=0) /
            (np.sum(power, axis=0) + 1e-10)
        )
        features['spectral_bandwidth_mean'] = float(np.mean(spread))
    else:
        features['spectral_centroid_mean'] = 0
        features['spectral_centroid_std'] = 0
        features['spectral_bandwidth_mean'] = 0
    # MFCC-like: mel-scale filterbank energies
    mel_bands = 13
    mel_low = 0
    mel_high = 2595 * np.log10(1 + sr / 2 / 700)
    mel_points = np.linspace(mel_low, mel_high, mel_bands + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bin_points = np.floor((len(wav) + 1) * hz_points / sr).astype(int)
    bin_points = np.clip(bin_points, 0, len(wav) - 1)
    fft = np.abs(np.fft.rfft(wav))
    fbank = np.zeros(mel_bands)
    for i in range(mel_bands):
        start = bin_points[i]
        mid = bin_points[i + 1]
        end = bin_points[i + 2]
        fbank[i] = np.mean(fft[start:end]) if end > start else 0
    features['mfcc_mean'] = float(np.mean(fbank))
    features['mfcc_std'] = float(np.std(fbank))
    return features


def build_feature_vector(features):
    """Flatten features into a vector for distance computation."""
    return np.array([
        features['rms'],
        features['zcr'],
        features['spectral_centroid_mean'] / 1000,
        features['spectral_bandwidth_mean'] / 1000,
        features['mfcc_mean'],
        features['mfcc_std'],
    ])


# ── Main ────────────────────────────────────────────────────────────

def main():
    # Load designs
    with open(DESIGNS_PATH, 'r', encoding='utf-8') as f:
        designs = json.load(f)

    # Collect all ref files
    ref_files = sorted(Path(REFS_DIR).glob('*.ogg'))
    if not ref_files:
        print(f'ERROR: No .ogg files found in {REFS_DIR}')
        sys.exit(1)

    print(f'Found {len(ref_files)} reference files in {REFS_DIR}')
    print()

    # ── Part 1: Basic stats ──────────────────────────────────────
    print('=' * 65)
    print('PART 1: BASIC STATS')
    print('=' * 65)

    durations = []
    durations_zh = []
    durations_en = []
    errors = []

    for rf in ref_files:
        try:
            wav, sr = sf.read(rf)
            dur = len(wav) / sr
            durations.append(dur)
            if '_zh_ref' in rf.name:
                durations_zh.append(dur)
            else:
                durations_en.append(dur)
        except Exception as e:
            errors.append((rf.name, str(e)))

    durations = np.array(durations)
    print(f'  ZH refs:  {len(durations_zh)} files, mean {np.mean(durations_zh):.1f}s, '
          f'min {np.min(durations_zh):.1f}s, max {np.max(durations_zh):.1f}s')
    print(f'  EN refs:  {len(durations_en)} files, mean {np.mean(durations_en):.1f}s, '
          f'min {np.min(durations_en):.1f}s, max {np.max(durations_en):.1f}s')
    if errors:
        print(f'  ERRORS:   {len(errors)} files')
        for name, err in errors[:5]:
            print(f'    {name}: {err}')
    print()

    # Check for very short files (< 1.0s)
    short_files = [rf for rf in ref_files if not Path(REFS_DIR, rf).is_file()]
    # Find short files manually
    short_list = []
    for rf in ref_files:
        try:
            wav, sr = sf.read(rf)
            if len(wav) / sr < 1.0:
                short_list.append((rf.name, len(wav) / sr))
        except:
            pass
    if short_list:
        print(f'  WARNING: {len(short_list)} files shorter than 1.0s:')
        for name, dur in short_list[:10]:
            print(f'    {name}: {dur:.2f}s')
        if len(short_list) > 10:
            print(f'    ... and {len(short_list) - 10} more')
    else:
        print('  All files >= 1.0s duration.')
    print()

    # ── Part 2: Per-design stats ─────────────────────────────────
    print('=' * 65)
    print('PART 2: PER-DESIGN DURATIONS')
    print('=' * 65)

    for did, design in sorted(designs['designs'].items()):
        npc_label = design.get('npc', did)
        zh_path = os.path.join(REFS_DIR, f'{did}_zh_ref.ogg')
        en_path = os.path.join(REFS_DIR, f'{did}_en_ref.ogg')
        zh_dur = 0
        en_dur = 0
        zh_ok = False
        en_ok = False
        if os.path.exists(zh_path):
            try:
                w, s = sf.read(zh_path)
                zh_dur = len(w) / s
                zh_ok = zh_dur >= 1.5
            except:
                pass
        if os.path.exists(en_path):
            try:
                w, s = sf.read(en_path)
                en_dur = len(w) / s
                en_ok = en_dur >= 1.5
            except:
                pass
        status = ''
        if not zh_ok:
            status += f' ZH:{zh_dur:.1f}s(SHORT!)'
        if not en_ok:
            status += f' EN:{en_dur:.1f}s(SHORT!)'
        if not status:
            status = f' ZH:{zh_dur:.1f}s EN:{en_dur:.1f}s OK'
        print(f'  [{npc_label:25s}] {status}')
    print()

    # ── Part 3: Feature analysis & distance ──────────────────────
    print('=' * 65)
    print('PART 3: VOICE DISTINCTIVENESS ANALYSIS')
    print('=' * 65)

    # Extract features for all refs
    feature_cache = {}
    for rf in ref_files:
        try:
            wav, sr = sf.read(rf)
            feats = extract_features(wav, sr)
            vec = build_feature_vector(feats)
            feature_cache[rf.stem] = {'features': feats, 'vector': vec}
        except Exception as e:
            print(f'  ERROR extracting features from {rf.name}: {e}')

    # Group by design (base name before _zh_ref or _en_ref)
    design_features = defaultdict(lambda: {'zh': None, 'en': None})
    for stem, data in feature_cache.items():
        if '_zh_ref' in stem:
            did = stem.replace('_zh_ref', '')
            design_features[did]['zh'] = data
        elif '_en_ref' in stem:
            did = stem.replace('_en_ref', '')
            design_features[did]['en'] = data

    design_ids = sorted(design_features.keys())
    print(f'  Extracted features for {len(design_ids)} designs '
          f'({len(feature_cache)} total audio files)')

    # 3a. ZH vs EN within same design (should be same voice, different language)
    within_design_distances = []
    for did in design_ids:
        d = design_features[did]
        if d['zh'] is not None and d['en'] is not None:
            dist = cosine(d['zh']['vector'], d['en']['vector'])
            within_design_distances.append(dist)

    within_design_distances = np.array(within_design_distances)
    print()
    print('  Within-design ZH↔EN cosine distance (should be LOW — same voice):')
    print(f'    Mean:  {np.mean(within_design_distances):.4f}')
    print(f'    Std:   {np.std(within_design_distances):.4f}')
    print(f'    Min:   {np.min(within_design_distances):.4f}')
    print(f'    Max:   {np.max(within_design_distances):.4f}')
    high_within = np.sum(within_design_distances > 0.15)
    if high_within > 0:
        print(f'    WARNING: {high_within} designs have ZH↔EN distance > 0.15')
        # List them
        for did in design_ids:
            d = design_features[did]
            if d['zh'] is not None and d['en'] is not None:
                dist = cosine(d['zh']['vector'], d['en']['vector'])
                if dist > 0.15:
                    design = designs['designs'].get(did, {})
                    label = design.get('npc', did)
                    print(f'      [{label:25s}] dist={dist:.4f}')
    print()

    # 3b. Across different designs (should be HIGH — different voices)
    design_vectors = {}
    for did in design_ids:
        d = design_features[did]
        if d['zh'] is not None:
            design_vectors[f'{did}_zh'] = d['zh']['vector']
        if d['en'] is not None:
            design_vectors[f'{did}_en'] = d['en']['vector']

    keys = list(design_vectors.keys())
    all_dists = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            d = cosine(design_vectors[keys[i]], design_vectors[keys[j]])
            all_dists.append(d)

    all_dists = np.array(all_dists)
    print('  Across-design cosine distance (should be HIGH — different voices):')
    print(f'    Mean:       {np.mean(all_dists):.4f}')
    print(f'    Std:        {np.std(all_dists):.4f}')
    print(f'    Min:        {np.min(all_dists):.4f}')
    print(f'    Max:        {np.max(all_dists):.4f}')

    # 3c. Most similar pairs (potential lack of distinctiveness)
    similar_pairs = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            d = cosine(design_vectors[keys[i]], design_vectors[keys[j]])
            similar_pairs.append((d, keys[i], keys[j]))
    similar_pairs.sort()
    print()
    print(f'  Top 10 most similar (lowest distance) design pairs:')
    for dist, k1, k2 in similar_pairs[:10]:
        did1 = k1.replace('_zh', '').replace('_en', '')
        did2 = k2.replace('_zh', '').replace('_en', '')
        d1 = designs['designs'].get(did1, {})
        d2 = designs['designs'].get(did2, {})
        label1 = d1.get('npc', did1)
        label2 = d2.get('npc', did2)
        print(f'    dist={dist:.4f}  [{label1:25s}] vs [{label2:25s}]')

    # 3d. Within-group vs between-group distances (for group designs)
    print()
    group_ids = [did for did in design_ids if did.startswith('group_')]
    unique_ids = [did for did in design_ids if not did.startswith('group_')]
    print(f'  Group designs: {len(group_ids)}, Unique designs: {len(unique_ids)}')

    # Groups vs groups
    group_group_dists = []
    for i in range(len(group_ids)):
        for j in range(i + 1, len(group_ids)):
            for lang1 in ['zh', 'en']:
                for lang2 in ['zh', 'en']:
                    d1 = design_features[group_ids[i]].get(lang1)
                    d2 = design_features[group_ids[j]].get(lang2)
                    if d1 is not None and d2 is not None:
                        group_group_dists.append(cosine(d1['vector'], d2['vector']))

    # Groups vs unique
    group_unique_dists = []
    for gid in group_ids:
        for uid in unique_ids:
            for lang1 in ['zh', 'en']:
                for lang2 in ['zh', 'en']:
                    d1 = design_features[gid].get(lang1)
                    d2 = design_features[uid].get(lang2)
                    if d1 is not None and d2 is not None:
                        group_unique_dists.append(cosine(d1['vector'], d2['vector']))

    if group_group_dists:
        print()
        print('  Group↔Group distance:')
        print(f'    Mean: {np.mean(group_group_dists):.4f}')
        print(f'    Min:  {np.min(group_group_dists):.4f}')
    if group_unique_dists:
        print('  Group↔Unique distance:')
        print(f'    Mean: {np.mean(group_unique_dists):.4f}')
        print(f'    Min:  {np.min(group_unique_dists):.4f}')

    # ── Summary ────────────────────────────────────────────────
    print()
    print('=' * 65)
    print('SUMMARY')
    print('=' * 65)
    print(f'  Total ref files:        {len(ref_files)}')
    print(f'  Designs:                {len(design_ids)}')
    print(f'  Mean duration:          {np.mean(durations):.1f}s')
    print(f'  Short files (<1.0s):    {len(short_list)}')
    print(f'  Errors:                 {len(errors)}')
    print(f'  Within-design distance:  {np.mean(within_design_distances):.4f} (expect < 0.1)')
    print(f'  Across-design distance:  {np.mean(all_dists):.4f} (expect > 0.1)')


if __name__ == '__main__':
    main()
