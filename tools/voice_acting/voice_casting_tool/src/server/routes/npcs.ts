import { Router } from 'express';
import fs from 'fs';
import path from 'path';
import db from '../db.js';
import { npcLines, CITY_MAP, PORTRAIT_FILES, VOICE_WAV_DIR } from '../index.js';

const router = Router();

// Precompute the "best sample" WAV per NPC: pick the longest line they say
// that also has a WAV on disk. Cached in-memory so it's free per request;
// rebuilds on demand.
let sampleWavCache: Record<string, string> = {};
let sampleWavCacheBuiltAt = 0;

function buildSampleWavCache(): Record<string, string> {
  const out: Record<string, string> = {};
  if (!VOICE_WAV_DIR) return out;
  for (const [name, lines] of Object.entries(npcLines)) {
    const candidates = [...lines].sort((a, b) => b.text.length - a.text.length);
    for (const l of candidates) {
      if (!l.filename) continue;
      try {
        if (fs.existsSync(path.join(VOICE_WAV_DIR, l.filename))) {
          out[name] = l.filename;
          break;
        }
      } catch { /* keep scanning */ }
    }
  }
  return out;
}

function getSampleWavs(): Record<string, string> {
  // Rebuild at most every 5 seconds - new WAVs can appear during generation
  // and we want the UI to pick them up without a server restart, but a
  // 5s TTL keeps the per-request cost near zero during normal browsing.
  const now = Date.now();
  if (now - sampleWavCacheBuiltAt > 5000) {
    sampleWavCache = buildSampleWavCache();
    sampleWavCacheBuiltAt = now;
  }
  return sampleWavCache;
}

router.get('/', (req, res) => {
  const assignments = db.prepare('SELECT * FROM assignments').all() as any[];
  const assignMap: Record<string, any> = {};
  for (const a of assignments) assignMap[a.npc_name] = a;

  const sampleWavs = getSampleWavs();

  const npcs = Object.entries(npcLines).map(([name, lines]) => ({
    name,
    city: CITY_MAP[name] || 'Unknown',
    portrait: PORTRAIT_FILES[name] || null,
    lineCount: lines.length,
    sampleWav: sampleWavs[name] || null,
    assignment: assignMap[name] ? {
      npcName: name,
      voiceId: assignMap[name].voice_id,
      voiceName: assignMap[name].voice_name,
      previewUrl: assignMap[name].preview_url,
      assignedAt: assignMap[name].assigned_at,
    } : null,
  }));

  npcs.sort((a, b) => a.name.localeCompare(b.name));
  res.json(npcs);
});

router.get('/:name/lines', (req, res) => {
  const lines = npcLines[req.params.name];
  if (!lines) return res.status(404).json({ error: 'NPC not found' });

  const out = lines.map(l => {
    let hasWav = false;
    if (VOICE_WAV_DIR && l.filename) {
      try { hasWav = fs.existsSync(path.join(VOICE_WAV_DIR, l.filename)); }
      catch { hasWav = false; }
    }
    return {
      text: l.text,
      filename: l.filename,
      offsetKey: l.offset_key,
      segment: parseInt(l.segment),
      voiceId: l.voice_id || '',
      voiceDesc: l.voice_desc || '',
      hasWav,
    };
  });
  res.json(out);
});

export default router;
