import React from 'react';
import type { Bookmark } from '../types';
import AudioPlayer from './AudioPlayer';
import { removeBookmark, assignVoice } from '../api';

interface Props {
  bookmarks: Bookmark[];
  currentNpc: string | null;
  onRefresh: () => void;
}

export default function BookmarkPanel({ bookmarks, currentNpc, onRefresh }: Props) {
  const handleAssign = async (b: Bookmark) => {
    if (!currentNpc) return;
    await assignVoice(currentNpc, b.voiceId, b.voiceName, b.previewUrl);
    onRefresh();
  };

  const handleDelete = async (voiceId: string) => {
    await removeBookmark(voiceId);
    onRefresh();
  };

  const btn = (color: string): React.CSSProperties => ({
    background: 'none', color, border: `1px solid ${color}`,
    padding: '3px 10px', fontSize: 12, cursor: 'pointer',
    fontFamily: 'var(--font-body)', transition: 'all 0.15s',
  });

  return (
    <div style={{
      width: 220, flexShrink: 0,
      background: 'var(--bg-panel)',
      borderLeft: '1px solid var(--border-dark)',
      display: 'flex', flexDirection: 'column',
      maxHeight: '100vh', overflow: 'hidden',
    }}>
      <div style={{
        padding: '14px 14px 10px', borderBottom: '1px solid var(--border-dark)',
      }}>
        <div style={{
          fontFamily: 'var(--font-display)', color: '#8a6aaa',
          fontSize: 14, marginBottom: 2,
        }}>
          Bookmarks
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
          {bookmarks.length} voice{bookmarks.length !== 1 ? 's' : ''} saved
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px' }}>
        {bookmarks.map(b => (
          <div key={b.voiceId} style={{
            background: 'var(--bg-card)', borderLeft: '2px solid var(--accent-purple)',
            padding: '8px 10px', marginBottom: 6, fontSize: 14,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 3 }}>
              {b.previewUrl && <AudioPlayer url={b.previewUrl} size="sm" />}
              <strong style={{
                color: 'var(--text-primary)', fontFamily: 'var(--font-display)',
                fontSize: 15, flex: 1,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>{b.voiceName}</strong>
            </div>
            {b.note && (
              <div style={{
                color: 'var(--text-secondary)', fontSize: 13,
                fontStyle: 'italic', marginBottom: 5, lineHeight: 1.3,
              }}>{b.note}</div>
            )}
            <div style={{ display: 'flex', gap: 4 }}>
              {currentNpc && (
                <button style={btn('var(--accent-green)')} onClick={() => handleAssign(b)}
                  onMouseOver={e => { e.currentTarget.style.background = 'var(--accent-green)'; e.currentTarget.style.color = '#d0e8c0'; }}
                  onMouseOut={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--accent-green)'; }}>
                  Assign to {currentNpc}
                </button>
              )}
              <button style={btn('var(--accent-red)')} onClick={() => handleDelete(b.voiceId)}
                onMouseOver={e => { e.currentTarget.style.background = 'var(--accent-red)'; e.currentTarget.style.color = '#f0c0c0'; }}
                onMouseOut={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--accent-red)'; }}>
                Remove
              </button>
            </div>
          </div>
        ))}
        {bookmarks.length === 0 && (
          <div style={{
            color: 'var(--text-dim)', fontSize: 13, fontStyle: 'italic',
            padding: 8, textAlign: 'center',
          }}>
            Bookmark voices while browsing to save them for later
          </div>
        )}
      </div>
    </div>
  );
}
