import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import type { VoiceAssignment, Npc } from '../types';
import AudioPlayer from './AudioPlayer';

interface Props {
  assignments: VoiceAssignment[];
  npcs: Npc[];
  totalNpcs: number;
}

const CITY_ORDER = [
  'Party', 'Trinsic', 'Britain', 'Paws', 'Cove', 'Minoc', 'Yew',
  'Jhelom', 'New Magincia', 'Skara Brae', 'Moonglow', 'Terfin',
  "Serpent's Hold", 'Vesper', "Buccaneer's Den", 'Forge of Virtue',
  'Ambrosia', 'Dagger Isle', 'Fellowship Retreat', 'Dungeon', 'Spektran', 'Endgame', 'Unknown',
];

export default function AssignmentsSidebar({ assignments, npcs, totalNpcs }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const currentNpc = location.pathname.startsWith('/npc/')
    ? decodeURIComponent(location.pathname.split('/npc/')[1]) : null;

  const pct = totalNpcs > 0 ? Math.round(assignments.length / totalNpcs * 100) : 0;

  const cityByName: Record<string, string> = {};
  for (const n of npcs) cityByName[n.name] = n.city || 'Unknown';

  const grouped: Record<string, VoiceAssignment[]> = {};
  for (const a of assignments) {
    const c = cityByName[a.npcName] || 'Unknown';
    if (!grouped[c]) grouped[c] = [];
    grouped[c].push(a);
  }
  for (const c of Object.keys(grouped)) {
    grouped[c].sort((a, b) => a.npcName.localeCompare(b.npcName));
  }
  const orderedCities = [
    ...CITY_ORDER.filter(c => grouped[c]),
    ...Object.keys(grouped).filter(c => !CITY_ORDER.includes(c)).sort(),
  ];

  return (
    <div style={{
      width: 240, flexShrink: 0,
      background: 'var(--bg-panel)',
      borderRight: '1px solid var(--border-dark)',
      display: 'flex', flexDirection: 'column',
      maxHeight: '100vh', overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 14px 10px', borderBottom: '1px solid var(--border-dark)',
      }}>
        <div style={{
          fontFamily: 'var(--font-display)', color: 'var(--accent-gold)',
          fontSize: 14, marginBottom: 6,
        }}>
          Voice Ledger
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 6 }}>
          {assignments.length} of {totalNpcs} assigned ({pct}%)
        </div>
        {/* Progress bar */}
        <div style={{
          height: 3, background: 'var(--bg-deep)', width: '100%',
        }}>
          <div style={{
            height: '100%', width: `${pct}%`,
            background: 'linear-gradient(90deg, var(--border-gold), var(--accent-gold))',
            transition: 'width 0.3s',
          }} />
        </div>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 4px' }}>
        {assignments.length === 0 && (
          <div style={{ color: 'var(--text-dim)', fontSize: 13, fontStyle: 'italic', padding: 8 }}>
            No voices assigned yet. Select an NPC to begin casting.
          </div>
        )}
        {orderedCities.map(city => (
          <div key={city} style={{ marginBottom: 10 }}>
            <div style={{
              fontFamily: 'var(--font-display)', fontSize: 12,
              color: city === 'Party' ? 'var(--accent-copper)' : 'var(--accent-gold)',
              padding: '4px 8px 2px', letterSpacing: '0.5px',
              borderBottom: '1px solid var(--border-dark)',
              display: 'flex', alignItems: 'baseline', gap: 6,
              marginBottom: 2,
            }}>
              <span>{city}</span>
              <span style={{
                fontSize: 12, color: 'var(--text-dim)',
                fontFamily: 'var(--font-body)',
              }}>
                {grouped[city].length}
              </span>
            </div>
            {grouped[city].map(a => {
              const isActive = currentNpc === a.npcName;
              return (
                <div
                  key={a.npcName}
                  onClick={() => navigate(`/npc/${encodeURIComponent(a.npcName)}`)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '4px 8px', cursor: 'pointer',
                    fontSize: 14,
                    background: isActive ? 'var(--bg-card)' : 'transparent',
                    borderLeft: isActive ? '2px solid var(--accent-gold)' : '2px solid transparent',
                    transition: 'all 0.1s',
                  }}
                  onMouseOver={e => { if (!isActive) e.currentTarget.style.background = 'var(--bg-card)'; }}
                  onMouseOut={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                >
                  <span style={{
                    flex: 1, color: isActive ? 'var(--accent-gold)' : 'var(--text-primary)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{a.npcName}</span>
                  <span style={{
                    color: 'var(--text-dim)', fontSize: 12,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    maxWidth: 70,
                  }}>{a.voiceName}</span>
                  {a.previewUrl && <AudioPlayer url={a.previewUrl} size="sm" />}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
