import React, { useRef, useState } from 'react';

interface Props {
  url: string;
  size?: 'sm' | 'md';
  tone?: 'gold' | 'green' | 'copper';
  title?: string;
  onRequestTooltip?: () => void;
  warn?: boolean;
}

const TONES = {
  gold:   { idle: 'var(--border-gold)',       idleEnd: '#6a5010', fg: 'var(--accent-gold)',   border: 'var(--border-gold)' },
  green:  { idle: 'var(--accent-green)',      idleEnd: '#2a4a1a', fg: '#d0e8c0',              border: 'var(--accent-green)' },
  copper: { idle: 'var(--accent-copper)',     idleEnd: '#6a3f1a', fg: '#f0c899',              border: 'var(--accent-copper)' },
};

export default function AudioPlayer({ url, size = 'sm', tone = 'gold', title, onRequestTooltip, warn = false }: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);

  const toggle = () => {
    if (!audioRef.current) {
      audioRef.current = new Audio(url);
      audioRef.current.onended = () => setPlaying(false);
      audioRef.current.onerror = () => setPlaying(false);
    }
    if (playing) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setPlaying(false);
    } else {
      audioRef.current.play();
      setPlaying(true);
    }
  };

  const isSmall = size === 'sm';
  const t = TONES[tone];

  return (
    <button
      onClick={e => { e.stopPropagation(); toggle(); }}
      onMouseEnter={() => onRequestTooltip?.()}
      onFocus={() => onRequestTooltip?.()}
      title={title}
      style={{
        background: playing
          ? 'linear-gradient(135deg, var(--accent-red), #6b2a2a)'
          : `linear-gradient(135deg, ${t.idle}, ${t.idleEnd})`,
        color: playing ? '#ffd0d0' : t.fg,
        border: `1px solid ${playing ? '#8b4a4a' : (warn ? 'var(--accent-red)' : t.border)}`,
        borderRadius: '50%',
        cursor: 'pointer',
        width: isSmall ? 22 : 28,
        height: isSmall ? 22 : 28,
        fontSize: isSmall ? 9 : 11,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        position: 'relative',
        transition: 'all 0.15s',
        boxShadow: playing
          ? '0 0 8px rgba(139,58,58,0.4)'
          : (warn ? '0 0 6px rgba(139,58,58,0.5)' : '0 0 4px rgba(139,105,20,0.2)'),
      }}
    >
      {playing ? '\u25A0' : '\u25B6'}
    </button>
  );
}
