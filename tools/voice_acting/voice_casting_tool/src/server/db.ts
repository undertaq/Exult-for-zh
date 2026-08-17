import Database from 'better-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DB_PATH = path.join(__dirname, '../../data/casting.db');

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

db.exec(`
  CREATE TABLE IF NOT EXISTS assignments (
    npc_name TEXT PRIMARY KEY,
    voice_id TEXT NOT NULL,
    voice_name TEXT,
    preview_url TEXT,
    assigned_at TEXT DEFAULT CURRENT_TIMESTAMP
  );
  CREATE TABLE IF NOT EXISTS bookmarks (
    voice_id TEXT PRIMARY KEY,
    voice_name TEXT,
    preview_url TEXT,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
  );
  CREATE TABLE IF NOT EXISTS generated_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    npc_name TEXT,
    voice_id TEXT,
    filename TEXT,
    text_hash TEXT,
    text TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
  );
`);

export default db;
