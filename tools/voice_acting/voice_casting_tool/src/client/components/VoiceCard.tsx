import React, { useState } from 'react';
import type { ElevenLabsVoice } from '../types';
import AudioPlayer from './AudioPlayer';

interface Props {
  voice: ElevenLabsVoice;
  currentNpc: string | null;
  usedBy: string[];
  onAssign: (voice: ElevenLabsVoice) => void;
  onBookmark: (voice: ElevenLabsVoice, note: string) => void;
}

export default function VoiceCard({ voice, currentNpc, usedBy, onAssign, onBookmark }: Props) {
  const usedByOthers = usedBy.filter(n => n !== currentNpc);
  const usedByCurrent = currentNpc && usedBy.includes(currentNpc);
  const [note, setNote] = useState('');
  const [showBookmark, setShowBookmark] = useState(false);

  const badge: React.CSSProperties = {
    background: 'var(--bg-deep)', border: '1px solid var(--border-dark)',
    padding: '2px 8px', fontSize: 12, color: 'var(--text-secondary)',
    letterSpacing: '0.3px', display: 'inline-block', marginRight: 4, marginBottom: 2,
  };

  const btn = (bg: string, fg: string, border: string): React.CSSProperties => ({
    background: bg, color: fg, border: `1px solid ${border}`,
    padding: '4px 14px', fontSize: 13, cursor: 'pointer',
    fontFamily: 'var(--font-body)', letterSpacing: '0.3px',
    transition: 'all 0.15s',
  });

  const leftBorder = usedByCurrent ? 'var(--accent-green)'
    : usedByOthers.length ? 'var(--accent-copper)'
    : 'var(--border-gold)';

  return (
    <div style={{
      background: 'var(--bg-card)', border: '1px solid var(--border-dark)',
      padding: '10px 12px', marginBottom: 6,
      borderLeft: `3px solid ${leftBorder}`,
      transition: 'border-color 0.15s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5, flexWrap: 'wrap' }}>
        {voice.preview_url && <AudioPlayer url={voice.preview_url} size="md" />}
        <strong style={{ fontFamily: 'var(--font-display)', color: 'var(--accent-gold)', fontSize: 15 }}>
          {voice.name}
        </strong>
        {usedByCurrent && (
          <span style={{
            fontSize: 11, padding: '2px 8px',
            background: 'var(--accent-green)', color: 'var(--bg-deep)',
            letterSpacing: '0.5px', fontWeight: 600,
          }}>CURRENT</span>
        )}
        {usedByOthers.length > 0 && (
          <span
            title={usedByOthers.join(', ')}
            style={{
              fontSize: 11, padding: '2px 8px',
              background: 'none', color: 'var(--accent-copper)',
              border: '1px solid var(--accent-copper)', letterSpacing: '0.3px',
            }}
          >
            In use by {usedByOthers.length === 1 ? usedByOthers[0]
              : `${usedByOthers[0]} +${usedByOthers.length - 1}`}
          </span>
        )}
      </div>
      <div style={{ marginBottom: 5 }}>
        {voice.gender && <span style={badge}>{voice.gender}</span>}
        {voice.age && <span style={badge}>{voice.age.replace(/_/g, ' ')}</span>}
        {voice.accent && <span style={badge}>{voice.accent}</span>}
        {voice.descriptive && (
          <span style={{
            ...badge, borderColor: 'var(--accent-copper)',
            color: 'var(--accent-copper)',
          }}>{voice.descriptive}</span>
        )}
        {voice.use_case && (
          <span style={{
            ...badge, borderColor: 'var(--accent-green)',
            color: 'var(--accent-green)',
          }}>{voice.use_case.replace(/_/g, ' ')}</span>
        )}
        {voice.category && (
          <span style={{
            ...badge, borderColor: 'var(--accent-purple)',
            color: '#8a6aaa',
          }}>{voice.category.replace(/_/g, ' ')}</span>
        )}
      </div>
      {voice.description && (
        <div style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 8, fontStyle: 'italic', lineHeight: 1.4 }}>
          {voice.description.slice(0, 140)}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {currentNpc && (
          <button style={btn('var(--accent-green)', '#d0e8c0', '#5a8a4a')} onClick={() => onAssign(voice)}
            onMouseOver={e => e.currentTarget.style.background = '#5a9a4a'}
            onMouseOut={e => e.currentTarget.style.background = 'var(--accent-green)'}>
            Assign to {currentNpc}
          </button>
        )}
        <button style={btn('none', '#8a6aaa', 'var(--accent-purple)')} onClick={() => setShowBookmark(!showBookmark)}
          onMouseOver={e => { e.currentTarget.style.background = 'var(--accent-purple)'; e.currentTarget.style.color = '#e0d0f0'; }}
          onMouseOut={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = '#8a6aaa'; }}>
          {showBookmark ? 'Cancel' : '\u2606 Bookmark'}
        </button>
      </div>
      {showBookmark && (
        <div style={{ marginTop: 8, display: 'flex', gap: 6 }}>
          <input
            value={note} onChange={e => setNote(e.target.value)}
            placeholder="Note: e.g., good for old wizard"
            style={{
              flex: 1, background: 'var(--bg-input)', color: 'var(--text-primary)',
              border: '1px solid var(--border-dark)', padding: '5px 10px',
              fontSize: 14, fontFamily: 'var(--font-body)',
              borderBottom: '1px solid var(--accent-purple)', outline: 'none',
            }}
          />
          <button style={btn('var(--accent-purple)', '#e0d0f0', '#7a5a9a')}
            onClick={() => { onBookmark(voice, note); setShowBookmark(false); setNote(''); }}>
            Save
          </button>
        </div>
      )}
    </div>
  );
}
