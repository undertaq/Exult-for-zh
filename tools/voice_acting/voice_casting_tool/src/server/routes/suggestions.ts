import { Router } from 'express';
import path from 'path';
import fs from 'fs';
import { parse } from 'csv-parse/sync';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CSV_PATH = path.join(
  __dirname, '../../../data/wiki_data/voice_suggestions.csv');

interface Suggestion {
  npc_name: string;
  gender: string;
  age: string;
  accent: string;
  descriptives: string[];
  use_cases: string[];
  confidence: string;
  reasoning: string;
}

const cache = new Map<string, Suggestion>();

function loadSuggestions() {
  cache.clear();
  if (!fs.existsSync(CSV_PATH)) {
    console.log(`No voice_suggestions.csv at ${CSV_PATH}`);
    return;
  }
  const raw = fs.readFileSync(CSV_PATH, 'utf-8');
  const rows = parse(raw, { columns: true, skip_empty_lines: true }) as any[];
  for (const r of rows) {
    cache.set(r.npc_name, {
      npc_name: r.npc_name,
      gender: r.gender || '',
      age: r.age || '',
      accent: r.accent || '',
      descriptives: r.descriptives ? r.descriptives.split('|').filter(Boolean) : [],
      use_cases: r.use_cases ? r.use_cases.split('|').filter(Boolean) : [],
      confidence: r.confidence || '',
      reasoning: r.reasoning || '',
    });
  }
  console.log(`Loaded ${cache.size} voice suggestions from ${CSV_PATH}`);
}

loadSuggestions();

const router = Router();

router.get('/:name', (req, res) => {
  const s = cache.get(req.params.name);
  if (!s) return res.status(404).json({ error: 'no suggestion' });
  res.json(s);
});

router.post('/reload', (_req, res) => {
  loadSuggestions();
  res.json({ loaded: cache.size });
});

export default router;
