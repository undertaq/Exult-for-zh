import { Router } from 'express';
import db from '../db.js';

const router = Router();

router.get('/', (req, res) => {
  const rows = db.prepare('SELECT * FROM bookmarks ORDER BY created_at DESC').all();
  res.json(rows);
});

router.post('/', (req, res) => {
  const { voice_id, voice_name, preview_url, note } = req.body;
  if (!voice_id) return res.status(400).json({ error: 'voice_id required' });

  db.prepare(`
    INSERT OR REPLACE INTO bookmarks (voice_id, voice_name, preview_url, note, created_at)
    VALUES (?, ?, ?, ?, datetime('now'))
  `).run(voice_id, voice_name || '', preview_url || '', note || '');

  res.json({ success: true });
});

router.delete('/:voice_id', (req, res) => {
  db.prepare('DELETE FROM bookmarks WHERE voice_id = ?').run(req.params.voice_id);
  res.json({ success: true });
});

export default router;
