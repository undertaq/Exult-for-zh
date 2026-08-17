import fs from 'fs';

// Minimal RIFF/WAVE LIST-INFO parser. Mirrors tools/voice_acting/wav_metadata.py
// so the same INAM/IART/ICMT chunks written by generate_voices.py are readable.

export interface WavMetadata {
  title: string;       // INAM - text hash
  artist: string;      // IART - e.g. "elevenlabs:<voice_id>"
  comment: string;     // ICMT - full text sent to TTS
  voiceSource: string; // parsed artist tag, e.g. "elevenlabs"
  voiceId: string;     // parsed artist tag, e.g. "<voice_id>"
}

export function readWavMetadata(filepath: string): WavMetadata {
  const empty: WavMetadata = {
    title: '', artist: '', comment: '', voiceSource: '', voiceId: '',
  };
  let data: Buffer;
  try {
    data = fs.readFileSync(filepath);
  } catch {
    return empty;
  }
  if (data.length < 12
      || data.toString('ascii', 0, 4) !== 'RIFF'
      || data.toString('ascii', 8, 12) !== 'WAVE') {
    return empty;
  }

  const result = { ...empty };
  let pos = 12;
  while (pos + 8 <= data.length) {
    const chunkId = data.toString('ascii', pos, pos + 4);
    const chunkSize = data.readUInt32LE(pos + 4);
    const chunkDataStart = pos + 8;

    if (chunkId === 'LIST' && chunkSize >= 4) {
      const listType = data.toString('ascii', chunkDataStart, chunkDataStart + 4);
      if (listType === 'INFO') {
        parseInfoSubchunks(
          data, chunkDataStart + 4,
          chunkDataStart + chunkSize, result);
      }
    }

    pos = chunkDataStart + chunkSize;
    if (pos % 2 !== 0) pos += 1; // word align
  }

  // Parse artist tag "<source>:<id>"
  if (result.artist.includes(':')) {
    const idx = result.artist.indexOf(':');
    result.voiceSource = result.artist.slice(0, idx);
    result.voiceId = result.artist.slice(idx + 1);
  } else if (result.artist) {
    result.voiceId = result.artist;
  }
  return result;
}

function parseInfoSubchunks(
  data: Buffer, start: number, end: number, result: WavMetadata,
): void {
  const tagMap: Record<string, keyof WavMetadata> = {
    INAM: 'title', IART: 'artist', ICMT: 'comment',
  };
  let pos = start;
  while (pos + 8 <= end) {
    const tag = data.toString('ascii', pos, pos + 4);
    const size = data.readUInt32LE(pos + 4);
    const valueStart = pos + 8;
    const valueEnd = Math.min(valueStart + size, end);
    const fieldName = tagMap[tag];
    if (fieldName) {
      let value = data.slice(valueStart, valueEnd);
      // Strip the null terminator and any even-alignment padding nulls.
      let endByte = value.length;
      while (endByte > 0 && value[endByte - 1] === 0) endByte--;
      value = value.slice(0, endByte);
      (result as any)[fieldName] = value.toString('utf-8');
    }
    pos = valueEnd;
    if (pos % 2 !== 0) pos += 1;
  }
}
