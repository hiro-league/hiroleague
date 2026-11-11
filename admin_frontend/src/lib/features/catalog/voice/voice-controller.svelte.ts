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
import { listCatalogModels, type CatalogModelRow } from '$lib/api/catalog';
import { listPeople, type Person } from '$lib/api/people';
import { errorMessage } from '$kit/api/client';
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
  /** The catalog's speech models (Google and OpenAI) for the editor's model picker. Loaded here, like the AI
   *  controller's chat models: the Catalog page's own model list only loads on its Models tab and follows that
   *  tab's filters, so the picker was empty when the page opened on Profiles. */
  speechModels = $state<CatalogModelRow[]>([]);
  speechModelsLoaded = $state(false);

  load = async () => {
    this.loading = true;
    // Step 1d: a failed request throws (answers are the data itself; there is no {ok, error} to test).
    // Only the profiles' failure is shown; any other failed read keeps what the page had.
    let profilesError: string | null = null;
    const [profiles, catalog, uses, people, prefs, speech] = await Promise.all([
      listVoiceProfiles().catch((err) => {
        profilesError = errorMessage(err);
        return null;
      }),
      getVoiceCatalog().catch(() => null),
      listVoiceUses().catch(() => null),
      listPeople().catch(() => null),
      // Hiro's voice lives in preferences; a failed read leaves it as it was (not "none").
      getPreferences().catch(() => null),
      // Speech models for the picker; a failed read keeps the last list.
      listCatalogModels({ model_kind: 'tts' }).catch(() => null)
    ]);
    if (speech)
      this.speechModels = speech.models.filter((m) => m.model_kind === 'tts' && /^(google|openai):/.test(m.id));
    this.speechModelsLoaded = true;
    if (prefs) this.hiroProfile = prefs.preferences.voice?.hiro_profile ?? null;
    this.loading = false;
    this.error = profilesError;
    if (profiles) this.profiles = profiles.profiles;
    if (catalog) this.catalog = catalog;
    if (uses) this.uses = uses;
    if (people) this.people = people.people.filter((p) => !!p.whatsapp);
  };

  /** Save a profile (new: `id` null → an id from its name). Resolves with its id; a refused save throws. */
  save = async (id: string | null, fields: VoiceProfileFields): Promise<string> => {
    const pid = id ?? voiceProfileId(fields.label, new Set(this.profiles.map((p) => p.id)));
    await patchPreferences({ [`voice.profiles.${pid}`]: fields });
    await this.load();
    return pid;
  };

  /** Delete a profile: the whole map without it, and the uses that pointed at it cleared. A refused delete throws. */
  remove = async (id: string): Promise<void> => {
    const rest = Object.fromEntries(this.profiles.filter((p) => p.id !== id).map((p) => [p.id, fieldsOf(p)]));
    const uses = Object.fromEntries(
      this.uses.extensions.flatMap((e) => e.uses.map((u) => [u.key, u.profile_id === id ? null : u.profile_id]))
    );
    // Phase 7b step 5: Hiro's voice can't name a missing profile; it goes to none with it.
    const hiro = this.hiroProfile === id ? { 'voice.hiro_profile': null } : {};
    await patchPreferences({ 'voice.profiles': rest, 'voice.uses': uses, ...hiro });
    await this.load();
  };

  /** Phase 7b step 5: Hiro's own voice (`voice.hiro_profile`); null = Hiro doesn't speak its replies.
   *  A refused save throws, and must not look saved. */
  setHiroProfile = async (profileId: string | null): Promise<void> => {
    await patchPreferences({ 'voice.hiro_profile': profileId });
    this.hiroProfile = profileId;
  };

  setUse = async (key: string, profileId: string | null): Promise<string | null> => {
    try {
      await setVoiceUse(key, profileId);
    } catch (err) {
      return errorMessage(err);
    }
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
