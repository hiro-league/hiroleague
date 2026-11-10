/**
 * Catalog → Profiles → Voice profiles (Phase 7b): the voice profiles, what a profile can use (models,
 * OpenAI's voices, sound tags), the extensions' voice uses, and the family members a take can be sent to.
 *
 * Profiles are saved through the preferences API (`voice.profiles.<id>`), like AI profiles; deleting one
 * writes the whole map and clears the uses that pointed at it.
 *
 * Phase 7b step 5: Hiro's own voice (`voice.hiro_profile`, read from the preferences payload) — the
 * Uses tab's "Speaking" row picks it; deleting the profile it names clears it too (the server refuses a
 * field naming a missing voice profile).
 */
import { listPeople, type Person } from '$lib/api/people';
import { getPreferences, patchPreferences } from '$lib/api/preferences';
import {
  getVoiceCatalog,
  listVoiceProfiles,
  listVoiceUses,
  setVoiceUse,
  type VoiceCatalog,
  type VoiceProfileFields,
  type VoiceProfileRow,
  type VoiceUses
} from '$lib/api/voice';

/** "Door alert" → "door-alert" (unique among `taken`). */
export function voiceProfileId(label: string, taken: Set<string>): string {
  const stem =
    label
      .toLowerCase()
      .normalize('NFKD')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 56) || 'voice';
  let id = stem;
  for (let n = 2; taken.has(id); n++) id = `${stem}-${n}`;
  return id;
}

export const fieldsOf = (r: VoiceProfileRow): VoiceProfileFields => ({
  label: r.label,
  model: r.model,
  voice: r.voice,
  voice_label: r.voice_label,
  style: r.style,
  speed: r.speed
});

export class VoiceController {
  profiles = $state<VoiceProfileRow[]>([]);
  catalog = $state<VoiceCatalog | null>(null);
  uses = $state<VoiceUses>({ extensions: [] });
  people = $state<Person[]>([]);
  loading = $state(false);
  error = $state<string | null>(null);
  /** Phase 7b step 5: the voice profile Hiro speaks its replies with (null = none). */
  hiroProfile = $state<string | null>(null);

  load = async () => {
    this.loading = true;
    const [profiles, catalog, uses, people, prefs] = await Promise.all([
      listVoiceProfiles(),
      getVoiceCatalog(),
      listVoiceUses(),
      listPeople(),
      // Hiro's voice lives in preferences; a failed read leaves it as it was (not "none").
      getPreferences().catch(() => null)
    ]);
    if (prefs?.ok && prefs.data) this.hiroProfile = prefs.data.preferences.voice?.hiro_profile ?? null;
    this.loading = false;
    this.error = !profiles.ok ? (profiles.error ?? 'Voice profiles could not be read.') : null;
    if (profiles.ok && profiles.data) this.profiles = profiles.data.profiles;
    if (catalog.ok && catalog.data) this.catalog = catalog.data;
    if (uses.ok && uses.data) this.uses = uses.data;
    if (people.ok && people.data) this.people = people.data.people.filter((p) => !!p.whatsapp);
  };

  /** Save a profile (new: `id` null → an id from its name). The answer is the error, or null. */
  save = async (id: string | null, fields: VoiceProfileFields): Promise<{ id: string } | { error: string }> => {
    const pid = id ?? voiceProfileId(fields.label, new Set(this.profiles.map((p) => p.id)));
    const res = await patchPreferences({ [`voice.profiles.${pid}`]: fields });
    if (!res.ok) return { error: res.error ?? 'Not saved.' };
    await this.load();
    return { id: pid };
  };

  /** Delete a profile: the whole map without it, and the uses that pointed at it cleared. */
  remove = async (id: string): Promise<string | null> => {
    const rest = Object.fromEntries(this.profiles.filter((p) => p.id !== id).map((p) => [p.id, fieldsOf(p)]));
    const uses = Object.fromEntries(
      this.uses.extensions.flatMap((e) => e.uses.map((u) => [u.key, u.profile_id === id ? null : u.profile_id]))
    );
    // Phase 7b step 5: Hiro's voice can't name a missing profile; it goes to none with it.
    const hiro = this.hiroProfile === id ? { 'voice.hiro_profile': null } : {};
    const res = await patchPreferences({ 'voice.profiles': rest, 'voice.uses': uses, ...hiro });
    if (!res.ok) return res.error ?? 'Not deleted.';
    await this.load();
    return null;
  };

  /** Phase 7b step 5: Hiro's own voice (`voice.hiro_profile`); null = Hiro doesn't speak its replies.
   *  The answer is the error, or null. */
  setHiroProfile = async (profileId: string | null): Promise<string | null> => {
    // patchPreferences answers { ok, error } rather than throwing: a refused save must not look saved.
    const res = await patchPreferences({ 'voice.hiro_profile': profileId });
    if (!res.ok) return res.error ?? 'Not saved.';
    this.hiroProfile = profileId;
    return null;
  };

  setUse = async (key: string, profileId: string | null): Promise<string | null> => {
    const res = await setVoiceUse(key, profileId);
    if (!res.ok) return res.error ?? 'Not saved.';
    await this.load();
    return null;
  };

  /** "home:speak" → "Home: Speak" (the use's declared name). */
  useLabel = (key: string): string => {
    const [ext] = key.split(':');
    const use = this.uses.extensions.flatMap((e) => e.uses).find((u) => u.key === key);
    return `${ext.charAt(0).toUpperCase()}${ext.slice(1)}: ${use?.name ?? key.split(':')[1]}`;
  };
}
