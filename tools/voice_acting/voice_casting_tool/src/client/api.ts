import type { Npc, DialogLine, VoiceSearchResult, VoiceAssignment, Bookmark, WikiEntry, VoiceFilterValues, VoiceSuggestion, ElevenLabsVoice, WavMetadata } from './types';

const BASE = '/api';

export async function fetchNpcs(): Promise<Npc[]> {
  const res = await fetch(`${BASE}/npcs`);
  return res.json();
}

export async function fetchNpcLines(name: string): Promise<DialogLine[]> {
  const res = await fetch(`${BASE}/npcs/${encodeURIComponent(name)}/lines`);
  return res.json();
}

export async function searchVoices(params: {
  q?: string; gender?: string; age?: string; accent?: string; language?: string;
  category?: string; use_cases?: string[]; descriptives?: string[];
  page?: number;
}): Promise<VoiceSearchResult> {
  const sp = new URLSearchParams();
  if (params.q) sp.set('q', params.q);
  if (params.gender) sp.set('gender', params.gender);
  if (params.age) sp.set('age', params.age);
  if (params.accent) sp.set('accent', params.accent);
  if (params.language) sp.set('language', params.language);
  if (params.category) sp.set('category', params.category);
  if (params.use_cases && params.use_cases.length) sp.set('use_cases', params.use_cases.join(','));
  if (params.descriptives && params.descriptives.length) sp.set('descriptives', params.descriptives.join(','));
  sp.set('page', String(params.page || 0));
  sp.set('page_size', '20');
  const res = await fetch(`${BASE}/voices/search?${sp}`);
  return res.json();
}

export async function fetchVoiceFilterValues(): Promise<VoiceFilterValues> {
  const res = await fetch(`${BASE}/voices/filter-values`);
  return res.json();
}

export async function fetchMyVoices(): Promise<{ voices: ElevenLabsVoice[] }> {
  const res = await fetch(`${BASE}/voices/my-voices`);
  if (!res.ok) return { voices: [] };
  return res.json();
}

export async function fetchVoiceSuggestion(npcName: string): Promise<VoiceSuggestion | null> {
  const res = await fetch(`${BASE}/suggestions/${encodeURIComponent(npcName)}`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchVoiceWavMetadata(filename: string): Promise<WavMetadata | null> {
  const res = await fetch(`${BASE}/voice-wavs/${encodeURIComponent(filename)}/metadata`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchGeneratedSampleMetadata(filename: string): Promise<WavMetadata | null> {
  const res = await fetch(`${BASE}/generate/${encodeURIComponent(filename)}/metadata`);
  if (!res.ok) return null;
  return res.json();
}

export async function assignVoice(npcName: string, voiceId: string, voiceName: string, previewUrl: string) {
  await fetch(`${BASE}/assignments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ npc_name: npcName, voice_id: voiceId, voice_name: voiceName, preview_url: previewUrl }),
  });
}

export async function removeAssignment(npcName: string) {
  await fetch(`${BASE}/assignments/${encodeURIComponent(npcName)}`, { method: 'DELETE' });
}

export async function fetchAssignments(): Promise<VoiceAssignment[]> {
  const res = await fetch(`${BASE}/assignments`);
  const rows = await res.json();
  return rows.map((r: any) => ({
    npcName: r.npc_name, voiceId: r.voice_id, voiceName: r.voice_name,
    previewUrl: r.preview_url, assignedAt: r.assigned_at,
  }));
}

export async function addBookmark(voiceId: string, voiceName: string, previewUrl: string, note: string) {
  await fetch(`${BASE}/bookmarks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ voice_id: voiceId, voice_name: voiceName, preview_url: previewUrl, note }),
  });
}

export async function fetchBookmarks(): Promise<Bookmark[]> {
  const res = await fetch(`${BASE}/bookmarks`);
  const rows = await res.json();
  return rows.map((r: any) => ({
    voiceId: r.voice_id, voiceName: r.voice_name, previewUrl: r.preview_url,
    note: r.note, createdAt: r.created_at,
  }));
}

export async function removeBookmark(voiceId: string) {
  await fetch(`${BASE}/bookmarks/${encodeURIComponent(voiceId)}`, { method: 'DELETE' });
}

export async function fetchWiki(npcName: string): Promise<WikiEntry | null> {
  const res = await fetch(`${BASE}/wiki/${encodeURIComponent(npcName)}`);
  if (!res.ok) return null;
  return res.json();
}

export async function generateSample(npcName: string, voiceId: string, text: string, prevText?: string, nextText?: string) {
  const res = await fetch(`${BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ npc_name: npcName, voice_id: voiceId, text, prev_text: prevText, next_text: nextText }),
  });
  return res.json();
}
