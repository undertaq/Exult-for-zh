import { Router } from 'express';
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import db from '../db.js';
import { readWavMetadata } from '../wavMetadata.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const GENERATED_DIR = path.join(__dirname, '../../../generated');

const router = Router();

const GENERATED_FILENAME_RE = /^[A-Za-z0-9._-]+\.wav$/;

router.get('/:filename/metadata', (req, res) => {
  const fn = req.params.filename;
  if (!GENERATED_FILENAME_RE.test(fn)) {
    return res.status(400).json({ error: 'bad filename' });
  }
  const p = path.join(GENERATED_DIR, fn);
  if (!fs.existsSync(p)) {
    return res.status(404).json({ error: 'not found' });
  }
  res.json(readWavMetadata(p));
});

function textHash(text: string): string {
  return crypto.createHash('sha256').update(text).digest('hex').slice(0, 16);
}

function writeWavWithMetadata(
  filepath: string, pcmData: Buffer,
  title: string, artist: string, comment: string
) {
  const sampleRate = 22050;
  const bitsPerSample = 16;
  const numChannels = 1;
  const byteRate = sampleRate * numChannels * bitsPerSample / 8;
  const blockAlign = numChannels * bitsPerSample / 8;
  const dataSize = pcmData.length;

  // fmt chunk
  const fmtChunk = Buffer.alloc(24);
  fmtChunk.write('fmt ', 0, 4, 'ascii');
  fmtChunk.writeUInt32LE(16, 4);
  fmtChunk.writeUInt16LE(1, 8); // PCM
  fmtChunk.writeUInt16LE(numChannels, 10);
  fmtChunk.writeUInt32LE(sampleRate, 12);
  fmtChunk.writeUInt32LE(byteRate, 16);
  fmtChunk.writeUInt16LE(blockAlign, 20);
  fmtChunk.writeUInt16LE(bitsPerSample, 22);

  // data chunk
  const dataHeader = Buffer.alloc(8);
  dataHeader.write('data', 0, 4, 'ascii');
  dataHeader.writeUInt32LE(dataSize, 4);

  // LIST INFO chunk
  const infoChunks: Buffer[] = [];
  for (const [tag, val] of [['INAM', title], ['IART', artist], ['ICMT', comment]]) {
    if (val) {
      const encoded = Buffer.from(val + '\0', 'utf-8');
      const padded = encoded.length % 2 !== 0 ? Buffer.concat([encoded, Buffer.alloc(1)]) : encoded;
      const header = Buffer.alloc(8);
      header.write(tag, 0, 4, 'ascii');
      header.writeUInt32LE(encoded.length, 4);
      infoChunks.push(Buffer.concat([header, padded]));
    }
  }
  const infoData = Buffer.concat([Buffer.from('INFO', 'ascii'), ...infoChunks]);
  const listHeader = Buffer.alloc(8);
  listHeader.write('LIST', 0, 4, 'ascii');
  listHeader.writeUInt32LE(infoData.length, 4);
  const listChunk = Buffer.concat([listHeader, infoData]);

  // RIFF header
  const waveBody = Buffer.concat([Buffer.from('WAVE', 'ascii'), fmtChunk, dataHeader, pcmData, listChunk]);
  const riffHeader = Buffer.alloc(8);
  riffHeader.write('RIFF', 0, 4, 'ascii');
  riffHeader.writeUInt32LE(waveBody.length, 4);

  fs.writeFileSync(filepath, Buffer.concat([riffHeader, waveBody]));
}

router.post('/', async (req, res) => {
  const { npc_name, voice_id, text, prev_text, next_text } = req.body;
  if (!voice_id || !text) return res.status(400).json({ error: 'voice_id and text required' });

  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) return res.status(500).json({ error: 'ELEVENLABS_API_KEY not set' });

  const hash = textHash(text);
  const filename = `cast_${npc_name || 'unknown'}_${hash}.wav`;
  const filepath = path.join(GENERATED_DIR, filename);

  // Check if already generated
  if (fs.existsSync(filepath)) {
    return res.json({ filename, url: `/generated/${filename}`, cached: true });
  }

  try {
    const response = await fetch(
      `https://api.elevenlabs.io/v1/text-to-speech/${voice_id}?output_format=pcm_22050`,
      {
        method: 'POST',
        headers: {
          'xi-api-key': apiKey,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          text,
          model_id: 'eleven_multilingual_v2',
          voice_settings: { stability: 0.5, similarity_boost: 0.75, style: 0.4, use_speaker_boost: true },
          ...(prev_text ? { previous_text: prev_text } : {}),
          ...(next_text ? { next_text: next_text } : {}),
        }),
      }
    );

    if (!response.ok) {
      return res.status(response.status).json({ error: await response.text() });
    }

    const pcmData = Buffer.from(await response.arrayBuffer());

    fs.mkdirSync(GENERATED_DIR, { recursive: true });
    writeWavWithMetadata(filepath, pcmData, hash, `elevenlabs:${voice_id}`, text);

    // Save to DB
    db.prepare(`
      INSERT INTO generated_samples (npc_name, voice_id, filename, text_hash, text)
      VALUES (?, ?, ?, ?, ?)
    `).run(npc_name || '', voice_id, filename, hash, text);

    res.json({ filename, url: `/generated/${filename}`, cached: false });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

export default router;
