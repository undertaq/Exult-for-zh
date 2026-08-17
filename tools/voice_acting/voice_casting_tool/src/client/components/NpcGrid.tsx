import React from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { Npc } from '../types';
import AudioPlayer from './AudioPlayer';

const CITY_ORDER = [
  'Party', 'Trinsic', 'Britain', 'Paws', 'Cove', 'Minoc', 'Yew',
  'Jhelom', 'New Magincia', 'Skara Brae', 'Moonglow', 'Terfin',
  "Serpent's Hold", 'Vesper', "Buccaneer's Den", 'Forge of Virtue',
  'Ambrosia', 'Dagger Isle', 'Fellowship Retreat', 'Dungeon', 'Spektran', 'Endgame', 'Unknown',
];

export default function NpcGrid({ npcs }: { npcs: Npc[] }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filter = params.get('q') || '';
  const unvoicedOnly = params.get('unvoiced') === '1';
  const cityFilter = params.get('city');

  const updateParams = (patch: Record<string, string | null>, replace = false) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace });
  };

  const setFilter = (v: string) => updateParams({ q: v || null }, true);
  const toggleUnvoiced = () => updateParams({ unvoiced: unvoicedOnly ? null : '1' });
  const setCityFilter = (v: string | null) => updateParams({ city: v });

  const filtered = npcs.filter(n => {
    if (unvoicedOnly && n.assignment) return false;
    if (cityFilter && (n.city || 'Unknown') !== cityFilter) return false;
    if (filter) {
      const q = filter.toLowerCase();
      if (!n.name.toLowerCase().includes(q) && !n.city.toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const byCity: Record<string, Npc[]> = {};
  for (const n of filtered) {
    const c = n.city || 'Unknown';
    if (!byCity[c]) byCity[c] = [];
    byCity[c].push(n);
  }

  const assigned = npcs.filter(n => n.assignment).length;
  const filterBtn = (active: boolean): React.CSSProperties => ({
    background: active ? 'var(--border-gold)' : 'none',
    color: active ? 'var(--bg-deep)' : 'var(--accent-gold)',
    border: '1px solid var(--border-gold)',
    padding: '8px 14px', fontSize: 13, cursor: 'pointer',
    fontFamily: 'var(--font-body)', letterSpacing: '0.3px',
    whiteSpace: 'nowrap', transition: 'all 0.15s',
  });

  return (
    <div style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 20, flexWrap: 'wrap' }}>
        <input
          placeholder="Search by name or city..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{
            flex: 1, minWidth: 220,
            background: 'var(--bg-input)', color: 'var(--text-primary)',
            border: '1px solid var(--border-dark)', padding: '10px 16px',
            fontSize: 15, fontFamily: 'var(--font-body)', outline: 'none',
            borderBottom: '2px solid var(--border-gold)',
          }}
        />
        <button
          style={filterBtn(unvoicedOnly)}
          onClick={toggleUnvoiced}
        >
          {unvoicedOnly ? '\u2713 Unvoiced only' : 'Unvoiced only'}
        </button>
        {cityFilter && (
          <button
            style={{ ...filterBtn(true), borderColor: 'var(--accent-copper)', background: 'var(--accent-copper)' }}
            onClick={() => setCityFilter(null)}
          >
            {cityFilter} &times;
          </button>
        )}
        <div style={{ fontSize: 14, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
          {assigned}/{npcs.length} voiced
        </div>
      </div>

      {CITY_ORDER.filter(c => byCity[c]).map(city => {
        const cityNpcs = byCity[city];
        const cityAssigned = cityNpcs.filter(n => n.assignment).length;
        const cityPct = cityNpcs.length > 0 ? Math.round(cityAssigned / cityNpcs.length * 100) : 0;
        return (
        <div key={city} style={{ marginBottom: 28 }}>
          <div style={{
            borderBottom: '1px solid var(--border-dark)', paddingBottom: 6, marginBottom: 12,
            display: 'flex', alignItems: 'baseline', gap: 10,
          }}>
            <button
              onClick={() => setCityFilter(cityFilter === city ? null : city)}
              title={cityFilter === city ? 'Clear city filter' : `Show only ${city}`}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontFamily: 'var(--font-display)', fontSize: 17,
                color: 'var(--accent-gold)', padding: 0,
                letterSpacing: '0.5px', transition: 'color 0.15s',
              }}
              onMouseOver={e => { e.currentTarget.style.color = '#e8c88c'; }}
              onMouseOut={e => { e.currentTarget.style.color = 'var(--accent-gold)'; }}
            >
              {city}
            </button>
            <span style={{ fontSize: 13, color: 'var(--text-dim)', fontFamily: 'var(--font-body)' }}>
              {cityNpcs.length} souls &middot; {cityAssigned} voiced ({cityPct}%)
            </span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {cityNpcs.map((npc, i) => (
              <div
                key={npc.name}
                onClick={() => navigate(`/npc/${encodeURIComponent(npc.name)}`)}
                style={{
                  background: 'var(--bg-card)', border: '1px solid var(--border-dark)',
                  padding: 12, cursor: 'pointer', width: 200,
                  display: 'flex', flexDirection: 'column', alignItems: 'center',
                  transition: 'all 0.15s',
                  animation: `fadeIn 0.3s ease-out ${i * 0.02}s both`,
                }}
                onMouseOver={e => {
                  e.currentTarget.style.borderColor = 'var(--border-gold)';
                  e.currentTarget.style.boxShadow = '0 0 12px rgba(139,105,20,0.15)';
                }}
                onMouseOut={e => {
                  e.currentTarget.style.borderColor = 'var(--border-dark)';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                {npc.portrait ? (
                  <div style={{
                    width: 112, height: 112, marginBottom: 10,
                    border: `1px solid ${npc.assignment ? 'var(--border-gold)' : 'var(--border-dark)'}`,
                    background: 'var(--bg-deep)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <img
                      src={`/portraits/${npc.portrait}`}
                      alt={npc.name}
                      style={{ width: 96, height: 96, imageRendering: 'pixelated' }}
                      onError={e => (e.target as HTMLImageElement).style.display = 'none'}
                    />
                  </div>
                ) : (
                  <div style={{
                    width: 112, height: 112, marginBottom: 10,
                    border: '1px solid var(--border-dark)', background: 'var(--bg-deep)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: 'var(--text-dim)', fontSize: 36,
                  }}>?</div>
                )}
                <div style={{
                  fontFamily: 'var(--font-display)', fontSize: 14,
                  color: 'var(--text-primary)', textAlign: 'center', lineHeight: 1.2,
                }}>{npc.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2 }}>
                  {npc.lineCount} lines
                </div>
                {npc.assignment ? (
                  <div style={{
                    fontSize: 13, color: 'var(--accent-gold)', marginTop: 4,
                    display: 'flex', alignItems: 'center', gap: 4,
                    maxWidth: '100%', overflow: 'hidden',
                  }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {npc.assignment.voiceName}
                    </span>
                    {npc.assignment.previewUrl && (
                      <AudioPlayer url={npc.assignment.previewUrl} size="sm"
                        title="ElevenLabs voice preview" />
                    )}
                    {npc.sampleWav && (
                      <AudioPlayer
                        url={`/api/voice-wavs/${encodeURIComponent(npc.sampleWav)}`}
                        size="sm" tone="green"
                        title="Play a line from the generated voice files on disk"
                      />
                    )}
                  </div>
                ) : (
                  <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 4, fontStyle: 'italic' }}>
                    unvoiced
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
        );
      })}

      {filtered.length === 0 && (
        <div style={{
          color: 'var(--text-dim)', fontSize: 14, fontStyle: 'italic',
          textAlign: 'center', padding: 40,
        }}>
          No NPCs match the current filters.
        </div>
      )}
    </div>
  );
}
