import { Router } from 'express';
import fs from 'fs';
import path from 'path';
import { VOICE_WAV_DIR } from '../index.js';
import { readWavMetadata } from '../wavMetadata.js';

const router = Router();

// Only allow a narrow filename shape - defense against path traversal and
// accidental hits to files outside the WAV dir.
const FILENAME_RE = /^[A-Za-z0-9._-]+\.wav$/;

function resolveSafe(filename: string): string | null {
  if (!VOICE_WAV_DIR) return null;
  if (!FILENAME_RE.test(filename)) return null;
  return path.join(VOICE_WAV_DIR, filename);
}

router.get('/_status', (_req, res) => {
  res.json({
    enabled: !!VOICE_WAV_DIR,
    dir: VOICE_WAV_DIR,
  });
});

// Stream a WAV from disk. Express's built-in sendFile is simpler than an
// open stream and handles range requests for audio scrubbing.
router.get('/:filename', (req, res) => {
  const p = resolveSafe(req.params.filename);
  if (!p) return res.status(404).json({ error: 'voice wav dir not configured or bad filename' });
  if (!fs.existsSync(p)) return res.status(404).json({ error: 'not found' });
  res.setHeader('Content-Type', 'audio/wav');
  res.sendFile(p);
});

// Read the embedded LIST-INFO metadata. Used by the UI to show the *actual*
// voice used when the WAV was generated, regardless of the current
// assignment.
router.get('/:filename/metadata', (req, res) => {
  const p = resolveSafe(req.params.filename);
  if (!p) return res.status(404).json({ error: 'voice wav dir not configured or bad filename' });
  if (!fs.existsSync(p)) return res.status(404).json({ error: 'not found' });
  const meta = readWavMetadata(p);
  res.json(meta);
});

export default router;
