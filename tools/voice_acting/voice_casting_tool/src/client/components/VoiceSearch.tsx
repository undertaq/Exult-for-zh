import React, { useState, useEffect, useCallback, useMemo } from 'react';
import type { ElevenLabsVoice, VoiceFilterValues, FilterValueEntry, VoiceSuggestion, VoiceAssignment } from '../types';
import { searchVoices, fetchVoiceFilterValues, fetchVoiceSuggestion, fetchMyVoices } from '../api';
import VoiceCard from './VoiceCard';

interface Props {
  currentNpc: string | null;
  assignments: VoiceAssignment[];
  onAssign: (voice: ElevenLabsVoice) => void;
  onBookmark: (voice: ElevenLabsVoice, note: string) => void;
}

// Accents grouped at the top for Ultima's Britannian setting. These render
// first (in this order); remaining accents follow by frequency.
const PRIORITY_ACCENTS = [
  'british', 'received pronunciation', 'irish', 'scottish', 'welsh',
  'standard', 'french', 'german', 'italian', 'spanish', 'peninsular',
  'dutch', 'swedish', 'portuguese', 'polish', 'russian',
];

// Descriptives to show as quick-filter chips above the results. Kept small
// so the row doesn't overwhelm; the full list is still in the picker.
const QUICK_DESCRIPTIVE_COUNT = 16;

// Fields we know take a small, enumerable set of values - these render as
// single-select dropdowns. Others (use_case, descriptive) are open-ended and
// render as a searchable multi-select chip picker.
const ENUM_FIELDS = {
  gender: 'Gender',
  age: 'Age',
  accent: 'Accent',
};

function titleCase(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function sortedValues(entries: FilterValueEntry[] | undefined): FilterValueEntry[] {
  // Already frequency-sorted from the backend. Fall back to alpha if no counts.
  return entries || [];
}

interface ChipPickerProps {
  label: string;
  selected: string[];
  onChange: (next: string[]) => void;
  options: FilterValueEntry[];
}

function ChipPicker({ label, selected, onChange, options }: ChipPickerProps) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');

  const visible = useMemo(() => {
    if (!filter) return options.slice(0, 40);
    const q = filter.toLowerCase();
    return options.filter(o => o.value.toLowerCase().includes(q)).slice(0, 40);
  }, [options, filter]);

  const toggle = (v: string) => {
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v]);
  };

  const buttonStyle: React.CSSProperties = {
    background: open || selected.length ? 'var(--bg-card)' : 'var(--bg-input)',
    color: selected.length ? 'var(--accent-gold)' : 'var(--text-primary)',
    border: '1px solid var(--border-dark)',
    borderBottom: `2px solid ${selected.length ? 'var(--accent-gold)' : 'var(--border-dark)'}`,
    padding: '8px 12px', fontSize: 14, cursor: 'pointer',
    fontFamily: 'var(--font-body)', minWidth: 120,
    display: 'flex', alignItems: 'center', gap: 6,
  };

  return (
    <div style={{ position: 'relative' }}>
      <button type="button" style={buttonStyle} onClick={() => setOpen(v => !v)}>
        <span>{label}</span>
        {selected.length > 0 && (
          <span style={{
            background: 'var(--accent-gold)', color: 'var(--bg-deep)',
            padding: '1px 6px', fontSize: 11, fontWeight: 600,
          }}>{selected.length}</span>
        )}
        <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>{open ? '\u25B2' : '\u25BC'}</span>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, marginTop: 2, zIndex: 10,
          background: 'var(--bg-panel)', border: '1px solid var(--border-gold)',
          boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
          width: 280, maxHeight: 340, overflow: 'hidden',
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ padding: 6, borderBottom: '1px solid var(--border-dark)' }}>
            <input
              autoFocus
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder={`Filter ${label.toLowerCase()}...`}
              style={{
                width: '100%', background: 'var(--bg-input)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-dark)', padding: '4px 8px',
                fontSize: 13, fontFamily: 'var(--font-body)', outline: 'none',
              }}
            />
          </div>
          <div style={{ overflowY: 'auto', padding: 4, flex: 1 }}>
            {selected.length > 0 && (
              <div style={{
                padding: '4px 6px', borderBottom: '1px solid var(--border-dark)',
                marginBottom: 4, display: 'flex', flexWrap: 'wrap', gap: 4,
              }}>
                {selected.map(s => (
                  <button key={s} onClick={() => toggle(s)} style={{
                    background: 'var(--accent-gold)', color: 'var(--bg-deep)',
                    border: 'none', padding: '2px 8px', fontSize: 12,
                    cursor: 'pointer', fontFamily: 'var(--font-body)',
                  }}>
                    {s} &times;
                  </button>
                ))}
                <button onClick={() => onChange([])} style={{
                  background: 'none', color: 'var(--accent-red)',
                  border: '1px solid var(--accent-red)', padding: '2px 8px',
                  fontSize: 12, cursor: 'pointer', fontFamily: 'var(--font-body)',
                }}>clear all</button>
              </div>
            )}
            {visible.map(opt => (
              <div
                key={opt.value}
                onClick={() => toggle(opt.value)}
                style={{
                  padding: '5px 8px', cursor: 'pointer', fontSize: 13,
                  display: 'flex', justifyContent: 'space-between',
                  background: selected.includes(opt.value) ? 'var(--bg-card)' : 'transparent',
                  color: selected.includes(opt.value) ? 'var(--accent-gold)' : 'var(--text-primary)',
                }}
                onMouseOver={e => { e.currentTarget.style.background = 'var(--bg-card)'; }}
                onMouseOut={e => {
                  e.currentTarget.style.background = selected.includes(opt.value) ? 'var(--bg-card)' : 'transparent';
                }}
              >
                <span>{titleCase(opt.value)}</span>
                <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{opt.count}</span>
              </div>
            ))}
            {visible.length === 0 && (
              <div style={{ padding: 8, color: 'var(--text-dim)', fontSize: 13, fontStyle: 'italic' }}>
                No matches
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function VoiceSearch({ currentNpc, assignments, onAssign, onBookmark }: Props) {
  // voiceId -> list of NPC names that have this voice assigned.
  const voiceUsage = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const a of assignments) {
      if (!map[a.voiceId]) map[a.voiceId] = [];
      map[a.voiceId].push(a.npcName);
    }
    return map;
  }, [assignments]);
  const [query, setQuery] = useState('');
  const [gender, setGender] = useState('');
  const [age, setAge] = useState('');
  const [accent, setAccent] = useState('');
  const [language, setLanguage] = useState('en');
  const [useCases, setUseCases] = useState<string[]>([]);
  const [descriptives, setDescriptives] = useState<string[]>([]);
  const [voices, setVoices] = useState<ElevenLabsVoice[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [filterVals, setFilterVals] = useState<VoiceFilterValues | null>(null);
  const [suggestion, setSuggestion] = useState<VoiceSuggestion | null>(null);
  const [suggestionDismissed, setSuggestionDismissed] = useState(false);
  const [myVoices, setMyVoices] = useState<ElevenLabsVoice[]>([]);
  const [showMyVoices, setShowMyVoices] = useState(false);

  useEffect(() => {
    fetchVoiceFilterValues().then(setFilterVals).catch(() => setFilterVals(null));
    fetchMyVoices().then(r => setMyVoices(r.voices || [])).catch(() => setMyVoices([]));
  }, []);

  useEffect(() => {
    setSuggestion(null);
    setSuggestionDismissed(false);
    if (currentNpc) {
      fetchVoiceSuggestion(currentNpc).then(setSuggestion).catch(() => setSuggestion(null));
    }
  }, [currentNpc]);

  const applySuggestion = () => {
    if (!suggestion) return;
    setGender(suggestion.gender);
    setAge(suggestion.age);
    setAccent(suggestion.accent);
    setUseCases(suggestion.use_cases);
    setDescriptives(suggestion.descriptives);
  };

  const doSearch = useCallback(async (p = 0, append = false) => {
    setLoading(true);
    try {
      const result = await searchVoices({
        q: query, gender, age, accent,
        language: language || undefined,
        use_cases: useCases, descriptives,
        page: p,
      });
      setVoices(prev => append ? [...prev, ...result.voices] : result.voices);
      setHasMore(result.hasMore);
      setTotalCount(result.totalCount);
      setPage(p);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }, [query, gender, age, accent, language, useCases, descriptives]);

  useEffect(() => {
    const timer = setTimeout(() => doSearch(0), 300);
    return () => clearTimeout(timer);
  }, [query, gender, age, accent, language, useCases, descriptives]);

  const inputBase: React.CSSProperties = {
    background: 'var(--bg-input)', color: 'var(--text-primary)',
    border: '1px solid var(--border-dark)', padding: '8px 12px',
    fontSize: 14, fontFamily: 'var(--font-body)', outline: 'none',
    borderBottom: '2px solid var(--border-gold)',
  };

  const selectBase: React.CSSProperties = {
    ...inputBase, fontSize: 14, padding: '8px 8px',
    borderBottom: '2px solid var(--border-dark)', cursor: 'pointer',
  };

  const genderOpts = sortedValues(filterVals?.values?.gender);
  const ageOpts = sortedValues(filterVals?.values?.age);
  const rawAccentOpts = sortedValues(filterVals?.values?.accent);
  // Put Western European accents first (in priority order), then the rest
  // by frequency.
  const accentOpts = useMemo(() => {
    const byValue: Record<string, FilterValueEntry> = {};
    for (const o of rawAccentOpts) byValue[o.value] = o;
    const top: FilterValueEntry[] = [];
    for (const v of PRIORITY_ACCENTS) {
      if (byValue[v]) { top.push(byValue[v]); delete byValue[v]; }
    }
    const rest = Object.values(byValue);  // already freq-sorted
    return [...top, ...rest];
  }, [rawAccentOpts]);
  const useCaseOpts = sortedValues(filterVals?.values?.use_case);
  const descriptiveOpts = sortedValues(filterVals?.values?.descriptive);
  const quickDescriptives = descriptiveOpts.slice(0, QUICK_DESCRIPTIVE_COUNT);

  const renderEnumSelect = (
    key: keyof typeof ENUM_FIELDS,
    value: string,
    setter: (v: string) => void,
    opts: FilterValueEntry[],
  ) => (
    <select style={selectBase} value={value} onChange={e => setter(e.target.value)}>
      <option value="">{ENUM_FIELDS[key]}</option>
      {opts.map(o => (
        <option key={o.value} value={o.value}>
          {titleCase(o.value)} ({o.count})
        </option>
      ))}
    </select>
  );

  const renderAccentSelect = () => {
    const prioritySet = new Set(PRIORITY_ACCENTS);
    const top = accentOpts.filter(o => prioritySet.has(o.value));
    const rest = accentOpts.filter(o => !prioritySet.has(o.value));
    return (
      <select style={selectBase} value={accent} onChange={e => setAccent(e.target.value)}>
        <option value="">Accent</option>
        {top.length > 0 && (
          <optgroup label="Western European">
            {top.map(o => (
              <option key={o.value} value={o.value}>
                {titleCase(o.value)} ({o.count})
              </option>
            ))}
          </optgroup>
        )}
        {rest.length > 0 && (
          <optgroup label="Other">
            {rest.map(o => (
              <option key={o.value} value={o.value}>
                {titleCase(o.value)} ({o.count})
              </option>
            ))}
          </optgroup>
        )}
      </select>
    );
  };

  const confColor = suggestion?.confidence === 'high' ? 'var(--accent-green)'
    : suggestion?.confidence === 'medium' ? 'var(--accent-copper)'
    : 'var(--text-dim)';

  return (
    <div>
      {suggestion && !suggestionDismissed && (
        <div style={{
          background: 'var(--bg-deep)', border: '1px solid var(--border-gold)',
          borderLeft: '3px solid var(--accent-copper)',
          padding: '10px 14px', marginBottom: 12,
          display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap',
        }}>
          <div style={{ flex: 1, minWidth: 260 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4,
              fontSize: 11, color: 'var(--text-dim)',
              textTransform: 'uppercase', letterSpacing: '1.5px',
            }}>
              <span>Suggested search</span>
              <span style={{
                color: confColor, fontWeight: 600, fontSize: 10,
              }}>{suggestion.confidence} confidence</span>
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-primary)', marginBottom: 6 }}>
              {[
                suggestion.gender, suggestion.age && suggestion.age.replace(/_/g, ' '),
                suggestion.accent,
                ...suggestion.descriptives,
                ...suggestion.use_cases.map(u => u.replace(/_/g, ' ')),
              ].filter(Boolean).join(' \u00B7 ')}
            </div>
            <div style={{
              fontSize: 13, color: 'var(--text-secondary)',
              fontStyle: 'italic', lineHeight: 1.4,
            }}>
              {suggestion.reasoning}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              onClick={applySuggestion}
              style={{
                background: 'var(--accent-copper)', color: 'var(--bg-deep)',
                border: '1px solid var(--accent-copper)', padding: '6px 14px',
                fontSize: 13, cursor: 'pointer', fontFamily: 'var(--font-body)',
                fontWeight: 600, letterSpacing: '0.3px',
              }}
            >Apply</button>
            <button
              onClick={() => setSuggestionDismissed(true)}
              style={{
                background: 'none', color: 'var(--text-dim)',
                border: '1px solid var(--border-dark)', padding: '6px 10px',
                fontSize: 13, cursor: 'pointer', fontFamily: 'var(--font-body)',
              }}
            >&times;</button>
          </div>
        </div>
      )}

      {myVoices.length > 0 && (
        <div style={{
          border: '1px solid var(--border-dark)',
          borderLeft: '3px solid var(--accent-purple)',
          marginBottom: 12, background: 'var(--bg-deep)',
        }}>
          <button
            onClick={() => setShowMyVoices(v => !v)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              width: '100%', padding: '8px 12px',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              color: 'var(--accent-purple)', fontFamily: 'var(--font-body)',
              fontSize: 13, letterSpacing: '0.3px',
            }}
          >
            <span>
              {showMyVoices ? '\u25BC' : '\u25B6'} My voices
              <span style={{ color: 'var(--text-dim)', fontSize: 12, marginLeft: 8 }}>
                ({myVoices.length} cloned / custom)
              </span>
            </span>
          </button>
          {showMyVoices && (
            <div style={{
              borderTop: '1px solid var(--border-dark)', padding: 8,
              maxHeight: 360, overflowY: 'auto',
            }}>
              {myVoices.map(v => (
                <VoiceCard
                  key={v.voice_id}
                  voice={v} currentNpc={currentNpc}
                  usedBy={voiceUsage[v.voice_id] || []}
                  onAssign={onAssign} onBookmark={onBookmark}
                />
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        <input
          style={{ ...inputBase, flex: 1, minWidth: 180 }}
          placeholder="Search the voice library..."
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        {renderEnumSelect('gender', gender, setGender, genderOpts)}
        {renderEnumSelect('age', age, setAge, ageOpts)}
        {renderAccentSelect()}
        <select style={selectBase} value={language} onChange={e => setLanguage(e.target.value)}>
          <option value="en">English</option>
          <option value="">Any Language</option>
        </select>
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        <ChipPicker
          label="Use case" selected={useCases} onChange={setUseCases}
          options={useCaseOpts}
        />
        <ChipPicker
          label="Descriptive" selected={descriptives} onChange={setDescriptives}
          options={descriptiveOpts}
        />
        {(useCases.length > 0 || descriptives.length > 0 || gender || age || accent) && (
          <button
            onClick={() => {
              setUseCases([]); setDescriptives([]);
              setGender(''); setAge(''); setAccent('');
            }}
            style={{
              background: 'none', color: 'var(--accent-red)',
              border: '1px solid var(--accent-red)', padding: '8px 14px',
              fontSize: 13, cursor: 'pointer', fontFamily: 'var(--font-body)',
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {quickDescriptives.length > 0 && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 4,
          marginBottom: 10, alignItems: 'center',
        }}>
          <span style={{
            fontSize: 11, color: 'var(--text-dim)',
            textTransform: 'uppercase', letterSpacing: '1px',
            marginRight: 4,
          }}>Descriptive:</span>
          {quickDescriptives.map(d => {
            const active = descriptives.includes(d.value);
            return (
              <button
                key={d.value}
                onClick={() => setDescriptives(
                  active ? descriptives.filter(x => x !== d.value) : [...descriptives, d.value]
                )}
                style={{
                  background: active ? 'var(--accent-copper)' : 'var(--bg-card)',
                  color: active ? 'var(--bg-deep)' : 'var(--text-secondary)',
                  border: `1px solid ${active ? 'var(--accent-copper)' : 'var(--border-dark)'}`,
                  padding: '3px 10px', fontSize: 12, cursor: 'pointer',
                  fontFamily: 'var(--font-body)', letterSpacing: '0.2px',
                  transition: 'all 0.1s',
                }}
                onMouseOver={e => { if (!active) e.currentTarget.style.borderColor = 'var(--accent-copper)'; }}
                onMouseOut={e => { if (!active) e.currentTarget.style.borderColor = 'var(--border-dark)'; }}
              >
                {titleCase(d.value)}
                <span style={{
                  marginLeft: 4, fontSize: 10,
                  color: active ? 'var(--bg-deep)' : 'var(--text-dim)',
                }}>{d.count}</span>
              </button>
            );
          })}
        </div>
      )}

      {loading && (
        <div style={{ color: 'var(--text-dim)', marginBottom: 8, fontSize: 14, fontStyle: 'italic' }}>
          Searching the archives...
        </div>
      )}
      {!loading && voices.length > 0 && (
        <div style={{ color: 'var(--text-dim)', marginBottom: 8, fontSize: 13 }}>
          Showing {voices.length} of {totalCount} voices
        </div>
      )}
      <div style={{ maxHeight: 500, overflowY: 'auto', paddingRight: 4 }}>
        {voices.map((v, i) => (
          <div key={v.voice_id} style={{ animation: `fadeIn 0.2s ease-out ${i * 0.03}s both` }}>
            <VoiceCard
              voice={v} currentNpc={currentNpc}
              usedBy={voiceUsage[v.voice_id] || []}
              onAssign={onAssign} onBookmark={onBookmark}
            />
          </div>
        ))}
        {hasMore && (
          <button
            onClick={() => doSearch(page + 1, true)}
            style={{
              background: 'none', color: 'var(--accent-gold)',
              border: '1px solid var(--border-gold)', padding: '8px 16px',
              cursor: 'pointer', width: '100%', fontFamily: 'var(--font-body)',
              fontSize: 14, letterSpacing: '0.5px', transition: 'all 0.15s',
            }}
            onMouseOver={e => { e.currentTarget.style.background = 'var(--border-gold)'; e.currentTarget.style.color = 'var(--bg-deep)'; }}
            onMouseOut={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--accent-gold)'; }}
          >
            Reveal more voices...
          </button>
        )}
      </div>
    </div>
  );
}
