import { Router } from 'express';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CACHE_DIR = path.join(__dirname, '../../../data/wiki_data/wiki_cache');

interface WikiEntry {
  npc_name: string;
  url: string;
  title: string;
  summary_html: string;
  summary_text: string;
  infobox: Record<string, string>;
  fetched_at: string;
}

function safeFilename(name: string): string {
  return name.replace(/[^A-Za-z0-9._-]/g, '_') + '.json';
}

const cache = new Map<string, WikiEntry>();

function loadCache() {
  cache.clear();
  if (!fs.existsSync(CACHE_DIR)) {
    console.log(`Wiki cache dir does not exist: ${CACHE_DIR}`);
    return;
  }
  const files = fs.readdirSync(CACHE_DIR).filter(f => f.endsWith('.json'));
  for (const f of files) {
    try {
      const raw = fs.readFileSync(path.join(CACHE_DIR, f), 'utf-8');
      const entry = JSON.parse(raw) as WikiEntry;
      cache.set(entry.npc_name, entry);
    } catch (e) {
      console.warn(`Failed to load wiki cache file ${f}:`, e);
    }
  }
  console.log(`Loaded ${cache.size} wiki entries from ${CACHE_DIR}`);
}

loadCache();

const router = Router();

router.get('/:name', (req, res) => {
  const name = req.params.name;
  const entry = cache.get(name);
  if (!entry) {
    const fsPath = path.join(CACHE_DIR, safeFilename(name));
    if (fs.existsSync(fsPath)) {
      try {
        const raw = fs.readFileSync(fsPath, 'utf-8');
        const parsed = JSON.parse(raw) as WikiEntry;
        cache.set(name, parsed);
        return res.json(parsed);
      } catch {
        /* fall through to 404 */
      }
    }
    return res.status(404).json({ error: 'no wiki entry for this NPC' });
  }
  res.json(entry);
});

router.post('/reload', (_req, res) => {
  loadCache();
  res.json({ loaded: cache.size });
});

export default router;
