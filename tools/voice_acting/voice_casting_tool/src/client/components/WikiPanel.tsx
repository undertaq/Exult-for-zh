import React, { useEffect, useState } from 'react';
import type { WikiEntry } from '../types';
import { fetchWiki } from '../api';

interface Props {
  npcName: string;
}

const INFOBOX_PRIORITY = [
  'Species', 'Race', 'Gender', 'Age',
  'Occupation', 'Job', 'Role', 'Title',
  'Location', 'Home', 'Town', 'City', 'Residence',
  'Affiliation', 'Faction', 'Alignment',
  'Family', 'Spouse', 'Relatives',
  'First Appearance', 'Last Appearance', 'Appears In',
];

function orderedInfoboxKeys(infobox: Record<string, string>): string[] {
  const keys = Object.keys(infobox);
  const used = new Set<string>();
  const out: string[] = [];
  for (const k of INFOBOX_PRIORITY) {
    const match = keys.find(x => x.toLowerCase() === k.toLowerCase() && !used.has(x));
    if (match) {
      out.push(match);
      used.add(match);
    }
  }
  for (const k of keys) {
    if (!used.has(k) && !k.toLowerCase().startsWith('image')
        && !k.toLowerCase().startsWith('portrait')
        && !k.toLowerCase().startsWith('caption')) {
      out.push(k);
    }
  }
  return out;
}

export default function WikiPanel({ npcName }: Props) {
  const [entry, setEntry] = useState<WikiEntry | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    setEntry(null);
    fetchWiki(npcName).then(e => {
      setEntry(e);
      setLoaded(true);
    });
  }, [npcName]);

  if (!loaded) return null;

  if (!entry) {
    return (
      <div style={{
        background: 'var(--bg-panel)', border: '1px solid var(--border-dark)',
        padding: 14, marginBottom: 16, fontSize: 13,
        color: 'var(--text-dim)', fontStyle: 'italic',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <span>No Ultima Codex wiki entry found for this character.</span>
        <a
          href={`https://wiki.ultimacodex.com/wiki/Special:Search?search=${encodeURIComponent(npcName)}`}
          target="_blank" rel="noopener noreferrer"
          style={{ color: 'var(--accent-copper)', fontSize: 12, textDecoration: 'none' }}
        >
          Search wiki &rarr;
        </a>
      </div>
    );
  }

  const keys = orderedInfoboxKeys(entry.infobox);

  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dark)',
      borderLeft: '3px solid var(--accent-copper)',
      padding: 18, marginBottom: 16,
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
        borderBottom: '1px solid var(--border-dark)', paddingBottom: 6, marginBottom: 12,
      }}>
        <h3 style={{
          fontFamily: 'var(--font-display)', color: 'var(--accent-copper)',
          fontSize: 16, fontWeight: 400,
        }}>
          Codex Entry &mdash; {entry.title}
        </h3>
        <a
          href={entry.url} target="_blank" rel="noopener noreferrer"
          style={{
            color: 'var(--accent-gold)', fontSize: 12,
            textDecoration: 'none', letterSpacing: '0.3px',
          }}
        >
          View on wiki &rarr;
        </a>
      </div>

      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        {keys.length > 0 && (
          <div style={{
            flex: '0 0 200px',
            background: 'var(--bg-deep)', border: '1px solid var(--border-dark)',
            padding: '10px 12px',
          }}>
            <div style={{
              fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase',
              letterSpacing: '1.5px', marginBottom: 6,
            }}>
              Details
            </div>
            <dl style={{ fontSize: 13, lineHeight: 1.5 }}>
              {keys.map(k => (
                <div key={k} style={{ marginBottom: 4 }}>
                  <dt style={{
                    color: 'var(--text-dim)', fontSize: 11,
                    textTransform: 'uppercase', letterSpacing: '0.5px',
                  }}>{k}</dt>
                  <dd style={{ color: 'var(--text-primary)', marginLeft: 0 }}>
                    {entry.infobox[k]}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        {entry.summary_text && (
          <div style={{
            flex: 1, minWidth: 260,
            fontSize: 14, lineHeight: 1.6,
            color: 'var(--text-primary)', fontFamily: 'var(--font-body)',
          }}>
            {entry.summary_text}
          </div>
        )}
      </div>
    </div>
  );
}
