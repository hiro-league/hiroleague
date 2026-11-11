/**
 * Voices (Phase 7b) — `/api/voice/...` (hirocli `admin_svelte/routes/voice.py` over `tools/voice.py`).
 * Voice profiles are created, changed and deleted through the preferences API (`voice.profiles.<id>`,
 * like `ai.profiles`); these routes read them, list Gemini's voices, design / add / delete our own,
 * Try a profile (takes play from `/voice/clips/<id>.ogg`) and manage `voice.uses`.
 */
import { base } from '$app/paths';
import { apiRequest } from './client';

export type VoiceSource = 'studio' | 'library' | 'mine';

/** A voice profile as preferences keep it (`voice.profiles.<id>`). */
export type VoiceProfileFields = {
  label: string;
  model: string; // catalog speech model, provider:model
  voice: string;
  voice_label: string;
  style: string;
  speed: number;
};

/** One row of `GET /voice/profiles`. */
export type VoiceProfileRow = VoiceProfileFields & {
  id: string;
  provider: string;
  line: string;
  /** Google still has the voice; null when not checked (OpenAI, or the list unreadable). */
  voice_ok: boolean | null;
  used_by: string[]; // voice use keys, "home:speak"
};

export type GeminiVoice = {
  id: string;
  name: string;
  source: VoiceSource;
  language: string | null;
  accent: string | null;
  gender: string | null;
  pitch: string | null;
  persona: string | null;
  description: string | null;
  expires: string | null; // ISO; designed voices only
};

export type VoiceCatalog = {
  models: { id: string; provider: string; name: string; key_set: boolean }[];
  openai_voices: string[];
  common_tags: string[];
  tag_groups: Record<string, string[]>;
  max_chars: number;
  design_languages: string[];
};

export type VoiceVoices = { voices: GeminiVoice[]; total: number; languages: { code: string; count: number }[] };

/** A clip made by Try it or a design (play it from `voiceClipUrl(id)`). */
export type VoiceClip = { id: string; seconds: number; bytes: number; took_s: number; cost_usd: number | null; cost_exact: boolean };

export type VoiceUseRow = { key: string; id: string; name: string; profile_id: string | null; status: 'ok' | 'removed' };
export type VoiceUses = { extensions: { extension: string; uses: VoiceUseRow[] }[] };

export type ClipCacheStats = { clips: number; bytes: number; hits: number; saved_usd: number; since: string | null; max_mb: number };

export const listVoiceProfiles = () => apiRequest<{ profiles: VoiceProfileRow[] }>('/voice/profiles', { timeoutMs: 60_000 });
export const getVoiceCatalog = () => apiRequest<VoiceCatalog>('/voice/catalog');

export function listVoices(q: {
  source?: VoiceSource;
  language?: string;
  gender?: string;
  q?: string;
  limit?: number;
  refresh?: boolean;
}): Promise<VoiceVoices> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== '' && v !== false) params.set(k, String(v));
  return apiRequest<VoiceVoices>(`/voice/voices?${params}`, { timeoutMs: 60_000 });
}

/** A voice's sample, to play in an <audio> (the core makes a prebuilt voice's once and keeps it). */
export const voiceSampleUrl = (voiceId: string) => `${base}/api/voice/voices/${encodeURIComponent(voiceId)}/sample`;
export const voiceClipUrl = (clipId: string, download = false) =>
  `${base}/api/voice/clips/${encodeURIComponent(clipId)}.ogg${download ? '?download=true' : ''}`;

export const designVoice = (body: { name: string; description: string; language?: string; gender?: string }) =>
  // Google takes about 30 s to make a voice.
  apiRequest<{ voice: GeminiVoice; clip: VoiceClip }>('/voice/voices', { method: 'POST', body, timeoutMs: 240_000 });
export const addVoice = (voiceId: string) =>
  apiRequest<{ voice_id: string }>('/voice/voices/add', { method: 'POST', body: { voice_id: voiceId }, timeoutMs: 60_000 });
export const deleteVoice = (voiceId: string) =>
  apiRequest<{ voice_id: string }>(`/voice/voices/${encodeURIComponent(voiceId)}`, { method: 'DELETE', timeoutMs: 60_000 });

export const tryVoice = (body: { text: string; profile_id?: string | null; draft?: VoiceProfileFields | null }) =>
  apiRequest<{ clip: VoiceClip }>('/voice/try', { method: 'POST', body, timeoutMs: 180_000 });
export const sendVoiceClip = (clipId: string, personId: string) =>
  apiRequest<{ sent: boolean; name: string }>(`/voice/clips/${encodeURIComponent(clipId)}/send`, {
    method: 'POST',
    body: { person_id: personId },
    timeoutMs: 70_000
  });

export const listVoiceUses = () => apiRequest<VoiceUses>('/voice/uses');
export const setVoiceUse = (key: string, profileId: string | null) =>
  apiRequest(`/voice/uses/${encodeURIComponent(key)}`, { method: 'PUT', body: { profile_id: profileId } });
export const getClipCache = () => apiRequest<ClipCacheStats>('/voice/clip-cache');
