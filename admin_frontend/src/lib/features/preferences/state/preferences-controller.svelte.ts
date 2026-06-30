import {
  getPreferences,
  normalizeWorkspacePreferences,
  patchPreferences,
  type PreferenceSection,
  type TuningProfile,
  type WorkspacePreferences
} from '$lib/api/preferences';
import { getPreferencesSchema } from '$lib/api/preferences-schema';
import {
  applyModelIdToDraft,
  type PrefModelIdPath
} from '$lib/features/preferences/shared/preferences-model-picker';
import { createLocalModelDownloads } from '$lib/features/preferences/state/local-model-downloads.svelte';
import { createModelCatalog } from '$lib/features/preferences/state/model-catalog.svelte';
import { createTuningProfiles } from '$lib/features/preferences/state/tuning-profiles.svelte';
import {
  cloneWorkspacePreferences,
  editsForSave,
  getPreferenceByPath,
  preferencesAreDirty,
  setPreferenceByPath
} from '$lib/features/preferences/state/preferences-edits';
import { PREFERENCES_FIELD_SCHEMA } from '$lib/api/preferences-field-schema';
import type { PreferencesSchemaMap } from '$lib/features/preferences/shared/preferences-schema';
import { createUnsavedGuard } from '$lib/navigation/unsaved-guard.svelte';
import type { ToastKind } from '$lib/ui/toast-types';

type Notify = (kind: ToastKind, message: string) => void;

export function createPreferencesController(notify: Notify) {
  // Composed stores: the model catalog (picker options + providers + active-providers + reload) and
  // the local-model download lifecycle. The controller re-exposes them through its public API.
  const catalog = createModelCatalog(notify);
  const downloads = createLocalModelDownloads(notify);

  let loading = $state(true);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let sections = $state<PreferenceSection[]>([]);
  // Built-in default texts for the editable system prompts (dotted path → text), from the
  // preferences payload. Powers the "Restore default" button: a cleared prompt persists "" and
  // the backend default only fills absent keys, so the UI can't recover the text on its own.
  let promptDefaults = $state<Record<string, string>>({});
  let fieldSchema = $state<PreferencesSchemaMap | null>(null);
  let baseline = $state<WorkspacePreferences | null>(null);
  let draft = $state<WorkspacePreferences | null>(null);
  let forceClean = $state(false);
  // Per-section validation errors (e.g. cross-field caps on the Retrieval Agent card).
  let sectionErrors = $state<Record<string, string | null>>({});

  const effectiveFieldSchema = $derived<PreferencesSchemaMap>(
    fieldSchema ?? PREFERENCES_FIELD_SCHEMA
  );

  const dirty = $derived.by(() => {
    if (forceClean || !baseline || !draft) return false;
    return preferencesAreDirty(baseline, draft, effectiveFieldSchema);
  });

  const hasSectionErrors = $derived(
    Object.values(sectionErrors).some((message) => message != null && message !== '')
  );
  const canSave = $derived(dirty && !busy && !loading && !hasSectionErrors);

  // Tuning-profile CRUD over the draft (create / duplicate / delete / update / defaults). `markDirty`
  // is a hoisted function declaration below.
  const profiles = createTuningProfiles({ draft: () => draft, markDirty });

  const unsaved = createUnsavedGuard(
    () => dirty,
    () => true,
    (next) => {
      forceClean = !next;
    }
  );

  function setDraftFromServer(prefs: WorkspacePreferences) {
    const normalized = normalizeWorkspacePreferences(prefs);
    baseline = cloneWorkspacePreferences(normalized);
    draft = cloneWorkspacePreferences(normalized);
    forceClean = false;
  }

  function sectionLabel(key: string, fallback: string): string {
    return (sections ?? []).find((section) => section.key === key)?.label ?? fallback;
  }

  function sectionDescription(key: string): string {
    return (sections ?? []).find((section) => section.key === key)?.description ?? '';
  }

  function markDirty() {
    forceClean = false;
  }

  function setSectionError(sectionId: string, message: string | null) {
    if (sectionErrors[sectionId] === message) return;
    sectionErrors = { ...sectionErrors, [sectionId]: message };
  }

  function setModelId(path: PrefModelIdPath, id: string | null) {
    if (!draft) return;
    if (applyModelIdToDraft(draft, path, id)) markDirty();
  }

  // Persist a SINGLE tuning profile to the backend immediately (the inline profile editor's
  // "Update"), independent of the page-level Save. Editing a shared profile applies to every
  // model referencing it. We diff just this profile's subtree so only its changed leaves PATCH,
  // then commit the result into both baseline and draft — leaving any other pending draft edits
  // untouched (so this never silently saves unrelated changes, and the page stays accurately dirty).
  async function saveProfileNow(id: string, next: TuningProfile) {
    if (!draft || !baseline || !draft.tuning_profiles[id]) return;
    busy = true;
    try {
      const probe = cloneWorkspacePreferences(baseline);
      probe.tuning_profiles[id] = next;
      const edits = editsForSave(baseline, probe, effectiveFieldSchema);
      if (Object.keys(edits).length === 0) return;
      const payload = await patchPreferences(edits);
      const saved = payload.data.preferences.tuning_profiles[id] ?? next;
      baseline.tuning_profiles[id] = JSON.parse(JSON.stringify(saved)) as TuningProfile;
      draft.tuning_profiles[id] = JSON.parse(JSON.stringify(saved)) as TuningProfile;
      notify('success', 'Tuning profile saved.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Save failed.');
    } finally {
      busy = false;
    }
  }

  // Persist one or more prompt paths to the backend IMMEDIATELY from a prompt-editor dialog,
  // independent of the page-level Save. The prompt cards no longer bind ctrl.draft directly (the
  // dialog edits a local working copy), so these paths normally sit equal in baseline and draft;
  // here we PATCH just the given edits and commit the server-effective values back into BOTH
  // baseline and draft for exactly those paths — leaving any other pending draft edits untouched
  // (so the page stays accurately dirty and never silently saves unrelated changes). Returns true
  // on success. `edits` is a dotted-path → value map (single prompt string, or whole writeWhole
  // dict for a prompt library), matching the page-save payload shape.
  async function saveDialogEdits(edits: Record<string, unknown>): Promise<boolean> {
    if (!draft || !baseline || Object.keys(edits).length === 0) return false;
    busy = true;
    try {
      const payload = await patchPreferences(edits);
      const saved = payload.data.preferences;
      for (const path of Object.keys(edits)) {
        const value = getPreferenceByPath(saved, path);
        // Clone so baseline and draft never share a mutable reference for the committed path.
        setPreferenceByPath(baseline, path, JSON.parse(JSON.stringify(value ?? null)));
        setPreferenceByPath(draft, path, JSON.parse(JSON.stringify(value ?? null)));
      }
      promptDefaults = payload.data.prompt_defaults ?? promptDefaults;
      sections = payload.data.sections ?? sections;
      notify('success', 'Prompt saved.');
      return true;
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Save failed.');
      return false;
    } finally {
      busy = false;
    }
  }

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [prefsPayload, schemaPayload] = await Promise.all([
        getPreferences(),
        getPreferencesSchema()
      ]);
      sections = prefsPayload.data.sections ?? [];
      promptDefaults = prefsPayload.data.prompt_defaults ?? {};
      fieldSchema = schemaPayload.ok ? (schemaPayload.data.fields ?? null) : null;
      const prefs = prefsPayload.data.preferences;
      setDraftFromServer(prefs);
      // Catalog options need the resolved prefs (to surface an unknown selected model); once prefs
      // are in, fetch the catalog and the download-status rows concurrently.
      await Promise.all([catalog.load(prefs), downloads.load()]);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load preferences.';
    } finally {
      loading = false;
    }
  }

  async function savePreferences() {
    if (!draft || !baseline || !canSave) return;
    const edits = editsForSave(baseline, draft, effectiveFieldSchema);
    if (Object.keys(edits).length === 0) return;
    busy = true;
    try {
      const payload = await patchPreferences(edits);
      sections = payload.data.sections ?? [];
      promptDefaults = payload.data.prompt_defaults ?? promptDefaults;
      setDraftFromServer(payload.data.preferences);
      notify('success', 'Workspace preferences saved.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Save failed.');
    } finally {
      busy = false;
    }
  }

  async function resetDraft() {
    if (!baseline) return;
    if (!(await unsaved.confirmDiscard())) return;
    abandonDraft();
  }

  function abandonDraft() {
    if (!baseline) return;
    draft = cloneWorkspacePreferences(baseline);
    forceClean = false;
  }

  return {
    get loading() {
      return loading;
    },
    get busy() {
      return busy;
    },
    get catalogReloadBusy() {
      return catalog.reloadBusy;
    },
    get error() {
      return error;
    },
    get draft() {
      return draft;
    },
    get promptDefaults() {
      return promptDefaults;
    },
    get fieldSchema() {
      // Live schema when loaded, else the committed mirror — so the Pref* field primitives keep
      // their bounds/hints even if GET /preferences/schema failed (never expose the raw null).
      return effectiveFieldSchema;
    },
    get dirty() {
      return dirty;
    },
    get canSave() {
      return canSave;
    },
    get profileEntries(): [string, TuningProfile][] {
      return profiles.profileEntries;
    },
    get chatOptions() {
      return catalog.chatOptions;
    },
    get sttOptions() {
      return catalog.sttOptions;
    },
    get ttsOptions() {
      return catalog.ttsOptions;
    },
    get embeddingOptions() {
      return catalog.embeddingOptions;
    },
    get localEmbedders() {
      return downloads.localEmbedders;
    },
    get embedderDownloading() {
      return downloads.embedderDownloading;
    },
    get embedderBusy() {
      return downloads.embedderBusy;
    },
    get rerankCatalogOptions() {
      return catalog.rerankCatalogOptions;
    },
    get rerankPickerOptions() {
      return catalog.rerankPickerOptions;
    },
    get localRerankers() {
      return downloads.localRerankers;
    },
    get rerankerDownloading() {
      return downloads.rerankerDownloading;
    },
    get rerankerBusy() {
      return downloads.rerankerBusy;
    },
    get catalogAllProviders() {
      return catalog.catalogAllProviders;
    },
    get activeProvidersStore() {
      return catalog.activeProvidersStore;
    },
    get unsaved() {
      return unsaved;
    },
    sectionLabel,
    sectionDescription,
    markDirty,
    setSectionError,
    setModelId,
    downloadReranker: downloads.downloadReranker,
    cancelReranker: downloads.cancelReranker,
    downloadEmbedder: downloads.downloadEmbedder,
    cancelEmbedder: downloads.cancelEmbedder,
    setDefaultTuningProfile: profiles.setDefaultTuningProfile,
    updateProfile: profiles.updateProfile,
    createProfile: profiles.createProfile,
    duplicateProfile: profiles.duplicateProfile,
    deleteProfile: profiles.deleteProfile,
    resetLockedProfile: profiles.resetLockedProfile,
    saveProfileNow,
    saveDialogEdits,
    loadAll,
    reloadCatalog: catalog.reload,
    savePreferences,
    resetDraft,
    abandonDraft
  };
}

export type PreferencesController = ReturnType<typeof createPreferencesController>;
