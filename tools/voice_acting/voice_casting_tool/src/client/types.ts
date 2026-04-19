export interface Npc {
  name: string;
  city: string;
  portrait: string | null;
  lineCount: number;
  sampleWav: string | null;
  assignment: VoiceAssignment | null;
}

export interface VoiceAssignment {
  npcName: string;
  voiceId: string;
  voiceName: string;
  previewUrl: string;
  assignedAt: string;
}

export interface DialogLine {
  text: string;
  filename: string;
  offsetKey: string;
  segment: number;
  voiceId: string;
  voiceDesc: string;
  hasWav: boolean;
}

export interface WavMetadata {
  title: string;
  artist: string;
  comment: string;
  voiceSource: string;
  voiceId: string;
}

export interface ElevenLabsVoice {
  voice_id: string;
  name: string;
  preview_url: string;
  description: string;
  gender: string;
  age: string;
  accent: string;
  category: string;
  use_case: string;
  descriptive: string;
  language: string;
}

export interface FilterValueEntry {
  value: string;
  count: number;
}

export interface VoiceSuggestion {
  npc_name: string;
  gender: string;
  age: string;
  accent: string;
  descriptives: string[];
  use_cases: string[];
  confidence: string;
  reasoning: string;
}

export interface VoiceFilterValues {
  scanned_voices: number;
  language_filter: string;
  values: Record<string, FilterValueEntry[]>;
}

export interface VoiceSearchResult {
  voices: ElevenLabsVoice[];
  hasMore: boolean;
  totalCount: number;
}

export interface Bookmark {
  voiceId: string;
  voiceName: string;
  previewUrl: string;
  note: string;
  createdAt: string;
}

export interface WikiEntry {
  npc_name: string;
  url: string;
  title: string;
  summary_html: string;
  summary_text: string;
  infobox: Record<string, string>;
  fetched_at: string;
}

export interface GeneratedSample {
  id: number;
  npcName: string;
  voiceId: string;
  filename: string;
  text: string;
  createdAt: string;
}
