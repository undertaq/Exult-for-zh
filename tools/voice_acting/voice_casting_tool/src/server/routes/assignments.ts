import { Router } from 'express';
import db from '../db.js';
import { CITY_MAP } from '../index.js';

const router = Router();

function csvEscape(s: unknown): string {
  const str = s == null ? '' : String(s);
  if (/[",\r\n]/.test(str)) return '"' + str.replace(/"/g, '""') + '"';
  return str;
}

router.get('/', (req, res) => {
  const rows = db.prepare('SELECT * FROM assignments ORDER BY npc_name').all();
  res.json(rows);
});

router.post('/', (req, res) => {
  const { npc_name, voice_id, voice_name, preview_url } = req.body;
  if (!npc_name || !voice_id) return res.status(400).json({ error: 'npc_name and voice_id required' });

  db.prepare(`
    INSERT OR REPLACE INTO assignments (npc_name, voice_id, voice_name, preview_url, assigned_at)
    VALUES (?, ?, ?, ?, datetime('now'))
  `).run(npc_name, voice_id, voice_name || '', preview_url || '');

  res.json({ success: true });
});

router.delete('/:npc_name', (req, res) => {
  db.prepare('DELETE FROM assignments WHERE npc_name = ?').run(req.params.npc_name);
  res.json({ success: true });
});

// Canonical CSV export for use by prepare_voice_lines.py etc.
// One row per assigned NPC; sorted by name. This is the source of truth.
router.get('/export.csv', (_req, res) => {
  const rows = db.prepare(
    'SELECT npc_name, voice_id, voice_name, preview_url, assigned_at ' +
    'FROM assignments ORDER BY npc_name'
  ).all() as any[];

  const header = ['npc_name', 'city', 'voice_id', 'voice_name', 'preview_url', 'assigned_at'];
  const lines = [header.join(',')];
  for (const r of rows) {
    lines.push([
      r.npc_name,
      CITY_MAP[r.npc_name] || '',
      r.voice_id,
      r.voice_name,
      r.preview_url,
      r.assigned_at,
    ].map(csvEscape).join(','));
  }
  const body = lines.join('\n') + '\n';

  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition',
    `attachment; filename="voice_assignments-${ts}.csv"`);
  res.send(body);
});

export default router;
