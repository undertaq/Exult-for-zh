import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { Npc, DialogLine, ElevenLabsVoice, VoiceAssignment } from '../types';
import { fetchNpcLines, assignVoice, generateSample, fetchVoiceWavMetadata, fetchGeneratedSampleMetadata } from '../api';
import type { WavMetadata } from '../types';
import VoiceSearch from './VoiceSearch';
import AudioPlayer from './AudioPlayer';
import WikiPanel from './WikiPanel';

const CITY_ORDER = [
  'Party', 'Trinsic', 'Britain', 'Paws', 'Cove', 'Minoc', 'Yew',
  'Jhelom', 'New Magincia', 'Skara Brae', 'Moonglow', 'Terfin',
  "Serpent's Hold", 'Vesper', "Buccaneer's Den", 'Forge of Virtue',
  'Ambrosia', 'Dagger Isle', 'Fellowship Retreat', 'Dungeon', 'Spektran', 'Endgame', 'Unknown',
];

function findNextUnvoiced(npcs: Npc[], currentName: string): Npc | null {
  // Traversal order: same as the main grid - iterate CITY_ORDER, then any
  // extra cities alphabetically; within each city, NPCs are already in the
  // alphabetical order the server returns. When we hit the end of a city,
  // continue into the next city in sequence.
  const byCity: Record<string, Npc[]> = {};
  for (const n of npcs) {
    const c = n.city || 'Unknown';
    if (!byCity[c]) byCity[c] = [];
    byCity[c].push(n);
  }
  const cities = [
    ...CITY_ORDER.filter(c => byCity[c]),
    ...Object.keys(byCity).filter(c => !CITY_ORDER.includes(c)).sort(),
  ];
  // Flatten into a single traversal order.
  const flat: Npc[] = [];
  for (const c of cities) flat.push(...byCity[c]);

  if (flat.length === 0) return null;
  const currentIdx = flat.findIndex(n => n.name === currentName);
  const start = currentIdx < 0 ? 0 : currentIdx + 1;
  // Wrap around once looking for an unvoiced NPC.
  for (let i = 0; i < flat.length; i++) {
    const n = flat[(start + i) % flat.length];
    if (n.name === currentName) continue;
    if (!n.assignment) return n;
  }
  return null;
}

interface Props {
  npcs: Npc[];
  assignments: VoiceAssignment[];
  onRefresh: () => void;
  onBookmark: (voice: ElevenLabsVoice, note: string) => void;
}

export default function NpcDetail({ npcs, assignments, onRefresh, onBookmark }: Props) {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [lines, setLines] = useState<DialogLine[]>([]);
  const [generatedUrls, setGeneratedUrls] = useState<Record<string, string>>({});
  const [generatedFilenames, setGeneratedFilenames] = useState<Record<string, string>>({});
  const [generating, setGenerating] = useState<string | null>(null);
  // filename -> metadata (cached after first hover). Keyed by the wav
  // filename on disk, so the same cache works for both disk samples and
  // generated samples (they live in different dirs but filenames are unique).
  const [metaCache, setMetaCache] = useState<Record<string, WavMetadata>>({});

  const loadMeta = async (filename: string, source: 'disk' | 'generated') => {
    if (metaCache[filename]) return;
    const m = source === 'disk'
      ? await fetchVoiceWavMetadata(filename)
      : await fetchGeneratedSampleMetadata(filename);
    if (m) setMetaCache(prev => ({ ...prev, [filename]: m }));
  };

  const npc = npcs.find(n => n.name === name);

  useEffect(() => {
    setLines([]);
    setGeneratedUrls({});
    setGeneratedFilenames({});
    setMetaCache({});
    if (name) fetchNpcLines(name).then(setLines);
  }, [name]);

  if (!npc || !name) return (
    <div style={{ color: 'var(--text-dim)', fontStyle: 'italic', padding: 40 }}>
      This soul is not found in the codex...
    </div>
  );

  const handleAssign = async (voice: ElevenLabsVoice) => {
    await assignVoice(name, voice.voice_id, voice.name, voice.preview_url);
    onRefresh();
  };

  const handleSteal = async (fromNpc: string) => {
    const a = assignments.find(a => a.npcName === fromNpc);
    if (a) {
      await assignVoice(name, a.voiceId, a.voiceName, a.previewUrl);
      onRefresh();
    }
  };

  const handleGenerate = async (line: DialogLine) => {
    if (!npc.assignment) return;
    setGenerating(line.filename);
    try {
      const result = await generateSample(name, npc.assignment.voiceId, line.text);
      setGeneratedUrls(prev => ({ ...prev, [line.filename]: result.url }));
      if (result.filename) {
        setGeneratedFilenames(prev => ({ ...prev, [line.filename]: result.filename }));
        // Invalidate any cached metadata for this filename - a fresh
        // generation for the same text/voice still overwrites the file on
        // disk, but voice/text can both have changed.
        setMetaCache(prev => {
          const next = { ...prev };
          delete next[result.filename];
          return next;
        });
      }
    } catch (e) {
      console.error(e);
    }
    setGenerating(null);
  };

  const buildTooltip = (filename: string, expectedText: string): string => {
    const m = metaCache[filename];
    if (!m) return 'Hover to load voice info...';
    const parts: string[] = [];
    if (m.voiceId) parts.push(`voice_id: ${m.voiceId}`);
    if (m.voiceSource) parts.push(`source: ${m.voiceSource}`);
    if (m.comment) {
      const matches = m.comment === expectedText;
      parts.push(matches ? 'text: matches current line' : 'text (DIFFERS): ' + m.comment.slice(0, 120));
    }
    return parts.join('\n') || '(no metadata)';
  };

  const otherAssignments = assignments.filter(a => a.npcName !== name);

  const section: React.CSSProperties = {
    background: 'var(--bg-panel)', border: '1px solid var(--border-dark)',
    padding: 18, marginBottom: 16,
  };

  const btn = (accent: string): React.CSSProperties => ({
    background: 'none', color: accent, border: `1px solid ${accent}`,
    padding: '5px 14px', fontSize: 14, cursor: 'pointer',
    fontFamily: 'var(--font-body)', letterSpacing: '0.3px', transition: 'all 0.15s',
  });

  const nextUnvoiced = findNextUnvoiced(npcs, name);

  return (
    <div style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button onClick={() => navigate(-1)} style={btn('var(--text-secondary)')}
          onMouseOver={e => { e.currentTarget.style.color = 'var(--accent-gold)'; e.currentTarget.style.borderColor = 'var(--accent-gold)'; }}
          onMouseOut={e => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.borderColor = 'var(--text-secondary)'; }}>
          &larr; Return to Codex
        </button>
        {nextUnvoiced && nextUnvoiced.name !== name && (
          <button onClick={() => navigate(`/npc/${encodeURIComponent(nextUnvoiced.name)}`)}
            style={btn('var(--accent-copper)')}
            onMouseOver={e => { e.currentTarget.style.background = 'var(--accent-copper)'; e.currentTarget.style.color = 'var(--bg-deep)'; }}
            onMouseOut={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--accent-copper)'; }}
            title={`Jump to ${nextUnvoiced.name} (${nextUnvoiced.city})`}>
            Next unvoiced: {nextUnvoiced.name} &rarr;
          </button>
        )}
      </div>

      {/* Character header */}
      <div style={{
        ...section,
        borderLeft: '3px solid var(--accent-gold)',
        display: 'flex', gap: 20, alignItems: 'flex-start',
      }}>
        <div style={{ flexShrink: 0 }}>
          {npc.portrait ? (
            <div style={{
              border: '2px solid var(--border-gold)', background: 'var(--bg-deep)',
              padding: 4, boxShadow: '0 0 20px rgba(139,105,20,0.1)',
            }}>
              <img src={`/portraits/${npc.portrait}`} alt={name}
                style={{ width: 80, height: 80, imageRendering: 'pixelated', display: 'block' }}
                onError={e => (e.target as HTMLImageElement).style.display = 'none'} />
            </div>
          ) : (
            <div style={{
              width: 88, height: 88, border: '2px solid var(--border-dark)',
              background: 'var(--bg-deep)', display: 'flex', alignItems: 'center',
              justifyContent: 'center', color: 'var(--text-dim)', fontSize: 28,
            }}>?</div>
          )}
        </div>
        <div style={{ flex: 1 }}>
          <h1 style={{
            fontFamily: 'var(--font-display)', color: 'var(--accent-gold)',
            fontSize: 26, fontWeight: 400, marginBottom: 4,
          }}>{name}</h1>
          <div style={{ color: 'var(--text-secondary)', fontSize: 15, marginBottom: 8 }}>
            {npc.city} &middot; {npc.lineCount} dialog lines
          </div>
          {npc.assignment ? (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: 'var(--bg-deep)', border: '1px solid var(--border-gold)',
              padding: '6px 12px', width: 'fit-content',
            }}>
              <span style={{ fontSize: 12, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '1px' }}>Voice:</span>
              <span style={{ color: 'var(--accent-gold)', fontFamily: 'var(--font-display)', fontSize: 16 }}>
                {npc.assignment.voiceName}
              </span>
              {npc.assignment.previewUrl && <AudioPlayer url={npc.assignment.previewUrl} size="md" />}
            </div>
          ) : (
            <div style={{ color: 'var(--text-dim)', fontStyle: 'italic', fontSize: 14 }}>
              No voice has been assigned to this character
            </div>
          )}
          {otherAssignments.length > 0 && (
            <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>Steal voice from:</span>
              <select onChange={e => e.target.value && handleSteal(e.target.value)}
                style={{
                  background: 'var(--bg-input)', color: 'var(--text-primary)',
                  border: '1px solid var(--border-dark)', padding: '4px 10px',
                  fontSize: 13, fontFamily: 'var(--font-body)', cursor: 'pointer',
                }}>
                <option value="">Choose...</option>
                {otherAssignments.map(a => (
                  <option key={a.npcName} value={a.npcName}>{a.npcName} ({a.voiceName})</option>
                ))}
              </select>
            </div>
          )}
        </div>
      </div>

      {/* Wiki entry */}
      <WikiPanel npcName={name} />

      {/* Voice search */}
      <div style={section}>
        <h3 style={{
          fontFamily: 'var(--font-display)', color: 'var(--accent-gold)',
          fontSize: 16, fontWeight: 400, marginBottom: 12,
          borderBottom: '1px solid var(--border-dark)', paddingBottom: 6,
        }}>
          Voice Library
        </h3>
        <VoiceSearch currentNpc={name} assignments={assignments} onAssign={handleAssign} onBookmark={onBookmark} />
      </div>

      {/* Dialog lines */}
      <div style={section}>
        <h3 style={{
          fontFamily: 'var(--font-display)', color: 'var(--accent-gold)',
          fontSize: 16, fontWeight: 400, marginBottom: 12,
          borderBottom: '1px solid var(--border-dark)', paddingBottom: 6,
        }}>
          Dialog &mdash; {lines.length} lines
        </h3>
        <div style={{ maxHeight: 600, overflowY: 'auto', paddingRight: 4 }}>
          {lines.map((line, i) => (
            <div key={line.filename} style={{
              background: 'var(--bg-card)', borderLeft: '2px solid var(--border-dark)',
              padding: '8px 12px', marginBottom: 4,
              display: 'flex', alignItems: 'center', gap: 8,
              animation: `fadeIn 0.2s ease-out ${i * 0.02}s both`,
            }}>
              <div style={{
                flex: 1, fontSize: 15, fontStyle: 'italic',
                color: 'var(--text-primary)', lineHeight: 1.4,
              }}>
                {line.text.slice(0, 180)}
              </div>
              <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
                {line.hasWav && (() => {
                  const m = metaCache[line.filename];
                  const mismatch = !!(m && npc.assignment && m.voiceId
                    && m.voiceId !== npc.assignment.voiceId);
                  return (
                    <AudioPlayer
                      url={`/api/voice-wavs/${encodeURIComponent(line.filename)}`}
                      size="md" tone="gold" warn={mismatch}
                      title={buildTooltip(line.filename, line.text)}
                      onRequestTooltip={() => loadMeta(line.filename, 'disk')}
                    />
                  );
                })()}
                {generatedUrls[line.filename] && (() => {
                  const fn = generatedFilenames[line.filename] || '';
                  const m = fn ? metaCache[fn] : undefined;
                  const mismatch = !!(m && npc.assignment && m.voiceId
                    && m.voiceId !== npc.assignment.voiceId);
                  return (
                    <AudioPlayer
                      url={generatedUrls[line.filename]}
                      size="md" tone="copper" warn={mismatch}
                      title={fn ? buildTooltip(fn, line.text) : undefined}
                      onRequestTooltip={fn ? () => loadMeta(fn, 'generated') : undefined}
                    />
                  );
                })()}
                {npc.assignment && (
                  <button
                    onClick={() => handleGenerate(line)}
                    disabled={generating === line.filename}
                    style={{
                      ...btn(generating === line.filename ? 'var(--text-dim)' : 'var(--accent-copper)'),
                      whiteSpace: 'nowrap', fontSize: 13,
                      cursor: generating === line.filename ? 'wait' : 'pointer',
                    }}
                  >
                    {generating === line.filename ? 'Forging...' : 'Forge Voice'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
