import { Router } from 'express';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FILTER_VALUES_PATH = path.join(
  __dirname, '../../../data/wiki_data/voice_filter_values.json');

const router = Router();

router.get('/search', async (req, res) => {
  const { q, gender, age, accent, language, category,
          use_cases, descriptives,
          page = '0', page_size = '20' } = req.query;
  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) return res.status(500).json({ error: 'ELEVENLABS_API_KEY not set' });

  const params = new URLSearchParams();
  if (q) params.set('search', q as string);
  if (gender) params.set('gender', gender as string);
  if (age) params.set('age', age as string);
  if (accent) params.set('accent', accent as string);
  if (language) params.set('language', language as string);
  if (category) params.set('category', category as string);

  // use_cases / descriptives are array params on the ElevenLabs side. We
  // accept them from the client as a comma-separated string (or an array)
  // and forward each value as a repeated query param.
  const appendArray = (key: string, val: unknown) => {
    if (!val) return;
    const items = Array.isArray(val)
      ? val
      : String(val).split(',').map(s => s.trim()).filter(Boolean);
    for (const item of items) params.append(key, item);
  };
  appendArray('use_cases', use_cases);
  appendArray('descriptives', descriptives);

  params.set('page', page as string);
  params.set('page_size', page_size as string);

  try {
    const response = await fetch(
      `https://api.elevenlabs.io/v1/shared-voices?${params}`,
      { headers: { 'xi-api-key': apiKey } }
    );
    if (!response.ok) {
      return res.status(response.status).json({ error: await response.text() });
    }
    const data = await response.json();
    res.json({
      voices: (data.voices || []).map((v: any) => ({
        voice_id: v.voice_id,
        name: v.name,
        preview_url: v.preview_url,
        description: v.description || '',
        gender: v.gender || '',
        age: v.age || '',
        accent: v.accent || '',
        category: v.category || '',
        use_case: v.use_case || '',
        descriptive: v.descriptive || '',
        language: v.language || '',
      })),
      hasMore: data.has_more || false,
      totalCount: data.total_count || 0,
    });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// List voices on the user's ElevenLabs account. Filters to only the voices
// the user owns (cloned or generated) - excludes the premade/public stock
// voices which are surfaced via /search. Useful for voices that aren't
// published to the shared voice library.
router.get('/my-voices', async (_req, res) => {
  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) return res.status(500).json({ error: 'ELEVENLABS_API_KEY not set' });
  try {
    const response = await fetch('https://api.elevenlabs.io/v1/voices', {
      headers: { 'xi-api-key': apiKey },
    });
    if (!response.ok) {
      return res.status(response.status).json({ error: await response.text() });
    }
    const data = await response.json();
    const owned = new Set(['cloned', 'generated', 'professional']);
    const voices = (data.voices || [])
      .filter((v: any) => owned.has(v.category))
      .map((v: any) => {
        const labels = v.labels || {};
        return {
          voice_id: v.voice_id,
          name: v.name,
          preview_url: v.preview_url || '',
          description: v.description || labels.description || '',
          gender: labels.gender || '',
          age: labels.age || '',
          accent: labels.accent || '',
          category: v.category || '',
          use_case: labels.use_case || '',
          descriptive: labels.descriptive || '',
          language: labels.language || '',
        };
      });
    res.json({ voices });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

router.get('/filter-values', (_req, res) => {
  if (!fs.existsSync(FILTER_VALUES_PATH)) {
    return res.json({
      scanned_voices: 0,
      language_filter: 'en',
      values: {},
      note: 'Run scripts/discover_voice_filters.py to populate this.',
    });
  }
  try {
    const raw = fs.readFileSync(FILTER_VALUES_PATH, 'utf-8');
    res.type('application/json').send(raw);
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

export default router;
