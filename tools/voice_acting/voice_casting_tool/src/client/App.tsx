import React, { useEffect, useState, useCallback } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
import type { Npc, VoiceAssignment, Bookmark, ElevenLabsVoice } from './types';
import { fetchNpcs, fetchAssignments, fetchBookmarks, addBookmark } from './api';
import NpcGrid from './components/NpcGrid';
import NpcDetail from './components/NpcDetail';
import AssignmentsSidebar from './components/AssignmentsSidebar';
import BookmarkPanel from './components/BookmarkPanel';

const globalStyle = `
  @import url('https://fonts.googleapis.com/css2?family=MedievalSharp&family=Crimson+Text:ital,wght@0,400;0,600;1,400&display=swap');

  :root {
    --bg-deep: #0e0c08;
    --bg-parchment: #1a1510;
    --bg-panel: #211d14;
    --bg-card: #2a2418;
    --bg-input: #1e1a12;
    --border-dark: #3a3020;
    --border-gold: #8b6914;
    --border-bright: #c4a265;
    --text-primary: #d4c4a0;
    --text-secondary: #9a8b6a;
    --text-dim: #6a5e48;
    --accent-gold: #c4a265;
    --accent-copper: #b87333;
    --accent-red: #8b3a3a;
    --accent-green: #4a7a3a;
    --accent-blue: #4a6a8a;
    --accent-purple: #6a4a7a;
    --font-display: 'MedievalSharp', cursive;
    --font-body: 'Crimson Text', Georgia, serif;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: var(--font-body);
    background: var(--bg-deep);
    color: var(--text-primary);
    background-image:
      radial-gradient(ellipse at 20% 50%, rgba(139,105,20,0.03) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 20%, rgba(184,115,51,0.02) 0%, transparent 50%);
  }

  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: var(--bg-deep); }
  ::-webkit-scrollbar-thumb { background: var(--border-gold); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--accent-gold); }

  ::selection { background: rgba(196,162,101,0.3); }

  input, select {
    font-family: var(--font-body);
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }
`;

export default function App() {
  const [npcs, setNpcs] = useState<Npc[]>([]);
  const [assignments, setAssignments] = useState<VoiceAssignment[]>([]);
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [showSidebar, setShowSidebar] = useState(true);
  const [showBookmarks, setShowBookmarks] = useState(true);
  const location = useLocation();

  const refresh = useCallback(async () => {
    const [n, a, b] = await Promise.all([fetchNpcs(), fetchAssignments(), fetchBookmarks()]);
    setNpcs(n);
    setAssignments(a);
    setBookmarks(b);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const currentNpc = location.pathname.startsWith('/npc/')
    ? decodeURIComponent(location.pathname.split('/npc/')[1])
    : null;

  const handleBookmark = async (voice: ElevenLabsVoice, note: string) => {
    await addBookmark(voice.voice_id, voice.name, voice.preview_url, note);
    const b = await fetchBookmarks();
    setBookmarks(b);
  };

  const toggleBtn: React.CSSProperties = {
    background: 'none', color: 'var(--accent-gold)', border: '1px solid var(--border-gold)',
    padding: '5px 16px', fontSize: 14, cursor: 'pointer', fontFamily: 'var(--font-body)',
    letterSpacing: '0.5px', transition: 'all 0.2s',
  };

  return (
    <>
      <style>{globalStyle}</style>
      <div style={{ display: 'flex', minHeight: '100vh' }}>
        {showSidebar && (
          <AssignmentsSidebar assignments={assignments} npcs={npcs} totalNpcs={npcs.length} />
        )}
        <div style={{ flex: 1, padding: '16px 24px', overflow: 'auto', minWidth: 0 }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            marginBottom: 20, paddingBottom: 12,
            borderBottom: '1px solid var(--border-dark)',
          }}>
            <div>
              <h1 style={{
                fontFamily: 'var(--font-display)', color: 'var(--accent-gold)',
                fontSize: 22, fontWeight: 400, letterSpacing: '1px',
              }}>
                Voice Casting Codex
              </h1>
              <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 2, letterSpacing: '1.5px', textTransform: 'uppercase' }}>
                Ultima VII &middot; The Black Gate
              </div>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <a
                href="/api/assignments/export.csv"
                download
                style={{
                  ...toggleBtn, borderColor: 'var(--accent-copper)',
                  color: 'var(--accent-copper)', textDecoration: 'none',
                  display: 'inline-flex', alignItems: 'center',
                }}
                onMouseOver={e => { e.currentTarget.style.background = 'var(--accent-copper)'; e.currentTarget.style.color = 'var(--bg-deep)'; }}
                onMouseOut={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--accent-copper)'; }}
                title="Download canonical NPC -> voice mapping CSV"
              >
                Export CSV
              </a>
              <button onClick={() => setShowSidebar(!showSidebar)} style={toggleBtn}
                onMouseOver={e => { e.currentTarget.style.background = 'var(--border-gold)'; e.currentTarget.style.color = 'var(--bg-deep)'; }}
                onMouseOut={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--accent-gold)'; }}>
                {showSidebar ? 'Hide' : 'Show'} Ledger
              </button>
              <button onClick={() => setShowBookmarks(!showBookmarks)} style={{...toggleBtn, borderColor: 'var(--accent-purple)', color: 'var(--accent-purple)'}}
                onMouseOver={e => { e.currentTarget.style.background = 'var(--accent-purple)'; e.currentTarget.style.color = 'var(--bg-deep)'; }}
                onMouseOut={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = '#8a6aaa'; }}>
                {showBookmarks ? 'Hide' : 'Show'} Marks
              </button>
            </div>
          </div>
          <Routes>
            <Route path="/" element={<NpcGrid npcs={npcs} />} />
            <Route path="/npc/:name" element={
              <NpcDetail npcs={npcs} assignments={assignments} onRefresh={refresh} onBookmark={handleBookmark} />
            } />
          </Routes>
        </div>
        {showBookmarks && (
          <BookmarkPanel bookmarks={bookmarks} currentNpc={currentNpc} onRefresh={refresh} />
        )}
      </div>
    </>
  );
}
