<script lang="ts">
  import { onMount } from 'svelte';
  import { BookOpen, KeyRound, RefreshCw, RotateCcw, Save, Settings2 } from '@lucide/svelte';
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import Button from '$lib/components/ui/button.svelte';
  import {
    listActiveProviders,
    listCatalogModels,
    listCatalogProviders,
    reloadModelCatalog,
    type ActiveProviderRow,
    type CatalogModelRow,
    type CatalogProviderRow
  } from '$lib/api/catalog';
  import {
    getPreferences,
    patchPreferences,
    type PreferenceSection,
    type WorkspacePreferences
  } from '$lib/api/preferences';
  import { createUnsavedGuard } from '$lib/navigation/unsaved-guard.svelte';
  import Modal from '$lib/ui/Modal.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import SingleModelPicker from './SingleModelPicker.svelte';

  type Toast = { kind: 'success' | 'error' | 'info' | 'warning'; message: string };
  type ModalityKey = 'voice' | 'image' | 'video' | 'file';

  const modalityKeys: ModalityKey[] = ['voice', 'image', 'video', 'file'];
  const modalityLabels: Record<ModalityKey, string> = {
    voice: 'Voice',
    image: 'Image',
    video: 'Video',
    file: 'File'
  };

  let loading = $state(true);
  let busy = $state(false);
  let catalogReloadBusy = $state(false);
  let error = $state<string | null>(null);
  let toast = $state<Toast | null>(null);
  let sections = $state<PreferenceSection[]>([]);
  let baseline = $state<WorkspacePreferences | null>(null);
  let draft = $state<WorkspacePreferences | null>(null);
  let tuningText = $state('{}');
  let forceClean = $state(false);

  let chatOptions = $state<CatalogModelRow[]>([]);
  let sttOptions = $state<CatalogModelRow[]>([]);
  let ttsOptions = $state<CatalogModelRow[]>([]);
  let catalogAllProviders = $state<CatalogProviderRow[]>([]);
  let activeProviders = $state<ActiveProviderRow[]>([]);
  let workspaceActiveProvidersResolved = $state(false);

  const dirty = $derived.by(() => {
    if (forceClean || !baseline || !draft) return false;
    return JSON.stringify(baseline) !== JSON.stringify(draft);
  });

  const tuningParse = $derived.by(() => {
    try {
      const parsed = JSON.parse(tuningText || '{}') as unknown;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return {
          value: null,
          error: 'Tuning must be a JSON object keyed by canonical model id.'
        };
      }
      return { value: parsed as WorkspacePreferences['llm']['tuning'], error: null };
    } catch (err) {
      return { value: null, error: err instanceof Error ? err.message : 'Invalid JSON.' };
    }
  });
  const parsedTuning = $derived(tuningParse.value);
  const tuningError = $derived(tuningParse.error);

  const canSave = $derived(dirty && !busy && !loading && tuningError === null);

  const chatActiveProviderIds = $derived(
    new Set(activeProviders.filter((row) => row.has_chat).map((row) => row.provider_id))
  );
  const sttActiveProviderIds = $derived(
    new Set(activeProviders.filter((row) => row.has_stt).map((row) => row.provider_id))
  );
  const ttsActiveProviderIds = $derived(
    new Set(activeProviders.filter((row) => row.has_tts).map((row) => row.provider_id))
  );

  const unsaved = createUnsavedGuard(
    () => dirty,
    () => true,
    (next) => {
      forceClean = !next;
    }
  );

  function notify(kind: Toast['kind'], message: string) {
    toast = { kind, message };
    window.setTimeout(() => {
      toast = null;
    }, 3600);
  }

  function clonePrefs(prefs: WorkspacePreferences): WorkspacePreferences {
    return JSON.parse(JSON.stringify(prefs)) as WorkspacePreferences;
  }

  function sectionLabel(key: string, fallback: string): string {
    return (sections ?? []).find((section) => section.key === key)?.label ?? fallback;
  }

  function sectionDescription(key: string): string {
    return (sections ?? []).find((section) => section.key === key)?.description ?? '';
  }

  function setDraft(prefs: WorkspacePreferences) {
    baseline = clonePrefs(prefs);
    draft = clonePrefs(prefs);
    tuningText = JSON.stringify(prefs.llm.tuning ?? {}, null, 2);
    forceClean = false;
  }

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [prefsPayload, chatPayload, sttPayload, ttsPayload, providersPayload] =
        await Promise.all([
          getPreferences(),
          listCatalogModels({ model_kind: 'chat' }),
          listCatalogModels({ model_kind: 'stt' }),
          listCatalogModels({ model_kind: 'tts' }),
          listCatalogProviders()
        ]);
      sections = prefsPayload.data.sections ?? [];
      setDraft(prefsPayload.data.preferences);
      chatOptions = prefsPayload.data.preferences.llm.default_chat
        ? includeUnknownModel(chatPayload.data.models, prefsPayload.data.preferences.llm.default_chat)
        : chatPayload.data.models;
      sttOptions = prefsPayload.data.preferences.llm.default_stt
        ? includeUnknownModel(sttPayload.data.models, prefsPayload.data.preferences.llm.default_stt)
        : sttPayload.data.models;
      ttsOptions = prefsPayload.data.preferences.llm.default_tts
        ? includeUnknownModel(ttsPayload.data.models, prefsPayload.data.preferences.llm.default_tts)
        : ttsPayload.data.models;
      catalogAllProviders = providersPayload.data;
      await loadActiveProviders();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load preferences.';
    } finally {
      loading = false;
    }
  }

  async function loadActiveProviders() {
    workspaceActiveProvidersResolved = false;
    try {
      const activePayload = await listActiveProviders();
      activeProviders = activePayload.data ?? [];
      workspaceActiveProvidersResolved = true;
    } catch {
      activeProviders = [];
      workspaceActiveProvidersResolved = false;
    }
  }

  function includeUnknownModel(models: CatalogModelRow[], id: string): CatalogModelRow[] {
    if (models.some((model) => model.id === id)) return models;
    const [providerId = 'unknown'] = id.split(':', 1);
    return [
      ...models,
      {
        id,
        provider_id: providerId || 'unknown',
        display_name: id,
        model_kind: 'chat'
      }
    ];
  }

  function markDirty() {
    forceClean = false;
  }

  function setDefaultModel(path: 'default_chat' | 'default_stt' | 'default_tts', id: string | null) {
    if (!draft) return;
    draft.llm[path] = id;
    markDirty();
  }

  function updateTuningText(next: string) {
    tuningText = next;
    if (!draft) return;
    try {
      const parsed = JSON.parse(next || '{}') as unknown;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return;
      draft.llm.tuning = parsed as WorkspacePreferences['llm']['tuning'];
      markDirty();
    } catch {
      markDirty();
    }
  }

  function editsForSave(): Record<string, unknown> {
    if (!baseline || !draft || !parsedTuning) return {};
    const edits: Record<string, unknown> = {};
    const add = (path: string, before: unknown, after: unknown) => {
      if (JSON.stringify(before) !== JSON.stringify(after)) edits[path] = after;
    };
    add('llm.default_chat', baseline.llm.default_chat, draft.llm.default_chat || null);
    add('llm.default_stt', baseline.llm.default_stt, draft.llm.default_stt || null);
    add('llm.default_tts', baseline.llm.default_tts, draft.llm.default_tts || null);
    add('llm.tuning', baseline.llm.tuning, parsedTuning);
    for (const key of modalityKeys) {
      add(`media.input.${key}`, baseline.media.input[key], draft.media.input[key]);
      add(`media.output.${key}`, baseline.media.output[key], draft.media.output[key]);
    }
    add('memory.max_messages', baseline.memory.max_messages, draft.memory.max_messages);
    return edits;
  }

  async function savePreferences() {
    if (!draft || !canSave) return;
    const edits = editsForSave();
    if (Object.keys(edits).length === 0) return;
    busy = true;
    try {
      const payload = await patchPreferences(edits);
      sections = payload.data.sections ?? [];
      setDraft(payload.data.preferences);
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
    draft = clonePrefs(baseline);
    tuningText = JSON.stringify(baseline.llm.tuning ?? {}, null, 2);
    forceClean = false;
  }

  async function reloadCatalogForPage() {
    catalogReloadBusy = true;
    try {
      const payload = await reloadModelCatalog();
      const [chatPayload, sttPayload, ttsPayload, providersPayload] = await Promise.all([
        listCatalogModels({ model_kind: 'chat' }),
        listCatalogModels({ model_kind: 'stt' }),
        listCatalogModels({ model_kind: 'tts' }),
        listCatalogProviders()
      ]);
      chatOptions = chatPayload.data.models;
      sttOptions = sttPayload.data.models;
      ttsOptions = ttsPayload.data.models;
      catalogAllProviders = providersPayload.data;
      await loadActiveProviders();
      notify(
        'success',
        `Catalog v${payload.data.catalog_version} reloaded (${payload.data.provider_count} providers, ${payload.data.model_count} models).`
      );
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Catalog reload failed.');
    } finally {
      catalogReloadBusy = false;
    }
  }

  onMount(() => {
    void loadAll();
  });
</script>

<svelte:head>
  <title>Preferences - Hiro Admin</title>
</svelte:head>

<ToastHost {toast} />

<div class="mx-auto grid w-full max-w-7xl gap-5">
  <header class="flex flex-col gap-3 border-b pb-5 lg:flex-row lg:items-start lg:justify-between">
    <div class="min-w-0">
      <h2 class="flex items-center gap-2 font-sans text-2xl font-bold text-foreground">
        <Settings2 size={22} /> Workspace Preferences
      </h2>
      <p class="mt-1 max-w-3xl text-sm text-muted-foreground">
        Runtime preferences are held in memory and persisted to preferences.json when saved.
      </p>
    </div>
  </header>

  <div
    class="sticky top-16 z-10 flex flex-col gap-3 border-b border-border/70 bg-background/95 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/85 lg:flex-row lg:items-center lg:justify-between"
  >
    <nav class="flex flex-wrap items-center gap-2" aria-label="Preference sections">
      <a
        class="inline-flex h-8 items-center rounded-md border border-input bg-background px-3 font-sans text-xs font-semibold text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        href="#preferences-models"
      >
        Models
      </a>
      <a
        class="inline-flex h-8 items-center rounded-md border border-input bg-background px-3 font-sans text-xs font-semibold text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        href="#preferences-media"
      >
        Media
      </a>
      <a
        class="inline-flex h-8 items-center rounded-md border border-input bg-background px-3 font-sans text-xs font-semibold text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        href="#preferences-memory"
      >
        Agent Memory
      </a>
    </nav>
    <div class="flex flex-wrap items-center gap-2 lg:justify-end">
      <Button variant="outline" disabled={busy} onclick={() => void goto(`${base}/active-providers/`)}>
        <KeyRound size={16} /> Active providers
      </Button>
      {#if dirty}
        <Button variant="outline" disabled={busy} onclick={() => void resetDraft()}>
          <RotateCcw size={16} /> Reset
        </Button>
        <Button disabled={!canSave} onclick={() => void savePreferences()}>
          <Save size={16} /> {busy ? 'Saving...' : 'Save'}
        </Button>
      {/if}
    </div>
  </div>

  {#if loading}
    <p class="text-sm text-muted-foreground">Loading preferences...</p>
  {:else if error}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
      {error}
    </div>
  {:else if draft}
    <section id="preferences-models" class="scroll-mt-32 grid gap-4 border-b pb-6">
      <div>
        <h3 class="font-sans text-xl font-semibold text-foreground">{sectionLabel('llm', 'Models')}</h3>
        <p class="mt-1 text-sm text-muted-foreground">{sectionDescription('llm')}</p>
      </div>
      <SingleModelPicker
        label="Default chat model"
        hint="Used when a character has no available preferred chat model."
        selectedId={draft.llm.default_chat}
        catalogModels={chatOptions}
        {catalogAllProviders}
        {workspaceActiveProvidersResolved}
        workspaceActiveProviderIds={chatActiveProviderIds}
        {busy}
        emptyProviders="No chat providers in catalog."
        emptyModelsForProvider="No chat models for this provider."
        onSelect={(id) => setDefaultModel('default_chat', id)}
        onChange={markDirty}
      >
        {#snippet toolbar()}
          <Button
            variant="outline"
            size="sm"
            class="shrink-0"
            disabled={busy}
            title="Open Model Catalog (bundled providers and models)"
            onclick={() => void goto(`${base}/catalog/`)}
          >
            <BookOpen size={14} /> Model catalog
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="shrink-0"
            disabled={busy || catalogReloadBusy}
            title="Reload bundled catalog.yaml on the server (clears in-memory cache)"
            onclick={() => void reloadCatalogForPage()}
          >
            <RefreshCw size={14} class={catalogReloadBusy ? 'animate-spin' : ''} /> Reload catalog
          </Button>
        {/snippet}
      </SingleModelPicker>
      <SingleModelPicker
        label="Default speech-to-text model"
        hint="Used for voice input transcription when voice input is enabled."
        selectedId={draft.llm.default_stt}
        catalogModels={sttOptions}
        {catalogAllProviders}
        {workspaceActiveProvidersResolved}
        workspaceActiveProviderIds={sttActiveProviderIds}
        {busy}
        emptyProviders="No speech-to-text providers in catalog."
        emptyModelsForProvider="No speech-to-text models for this provider."
        onSelect={(id) => setDefaultModel('default_stt', id)}
        onChange={markDirty}
      >
        {#snippet toolbar()}
          <Button
            variant="outline"
            size="sm"
            class="shrink-0"
            disabled={busy}
            title="Open Model Catalog (bundled providers and models)"
            onclick={() => void goto(`${base}/catalog/`)}
          >
            <BookOpen size={14} /> Model catalog
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="shrink-0"
            disabled={busy || catalogReloadBusy}
            title="Reload bundled catalog.yaml on the server (clears in-memory cache)"
            onclick={() => void reloadCatalogForPage()}
          >
            <RefreshCw size={14} class={catalogReloadBusy ? 'animate-spin' : ''} /> Reload catalog
          </Button>
        {/snippet}
      </SingleModelPicker>
      <SingleModelPicker
        label="Default text-to-speech model"
        hint="Used as the voice reply fallback when a character has no available TTS model."
        selectedId={draft.llm.default_tts}
        catalogModels={ttsOptions}
        {catalogAllProviders}
        {workspaceActiveProvidersResolved}
        workspaceActiveProviderIds={ttsActiveProviderIds}
        {busy}
        emptyProviders="No text-to-speech providers in catalog."
        emptyModelsForProvider="No text-to-speech models for this provider."
        onSelect={(id) => setDefaultModel('default_tts', id)}
        onChange={markDirty}
      />
      <label class="grid gap-2">
        <span class="font-sans text-sm font-semibold text-muted-foreground">Model tuning JSON</span>
        <textarea
          class="min-h-40 rounded-md border border-input bg-background px-3 py-2 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          spellcheck="false"
          value={tuningText}
          oninput={(event) => updateTuningText(event.currentTarget.value)}
        ></textarea>
      </label>
      {#if tuningError}
        <p class="text-sm text-destructive">{tuningError}</p>
      {/if}
    </section>

    <section id="preferences-media" class="scroll-mt-32 grid gap-4 border-b pb-6">
      <div>
        <h3 class="font-sans text-xl font-semibold text-foreground">{sectionLabel('media', 'Media')}</h3>
        <p class="mt-1 text-sm text-muted-foreground">{sectionDescription('media')}</p>
      </div>
      <div class="grid gap-4 lg:grid-cols-2">
        <div class="grid gap-3 rounded-md border border-border/70 bg-background/45 p-4">
          <h4 class="font-sans text-base font-semibold text-foreground">Input modalities</h4>
          {#each modalityKeys as key (key)}
            <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
              <input
                type="checkbox"
                bind:checked={draft.media.input[key]}
                onchange={markDirty}
              />
              <span class="font-sans text-sm font-medium">{modalityLabels[key]}</span>
            </label>
          {/each}
        </div>
        <div class="grid gap-3 rounded-md border border-border/70 bg-background/45 p-4">
          <h4 class="font-sans text-base font-semibold text-foreground">Output modalities</h4>
          {#each modalityKeys as key (key)}
            <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
              <input
                type="checkbox"
                bind:checked={draft.media.output[key]}
                onchange={markDirty}
              />
              <span class="font-sans text-sm font-medium">{modalityLabels[key]}</span>
            </label>
          {/each}
        </div>
      </div>
    </section>

    <section id="preferences-memory" class="scroll-mt-32 grid gap-4">
      <div>
        <h3 class="font-sans text-xl font-semibold text-foreground">
          {sectionLabel('memory', 'Agent Memory')}
        </h3>
        <p class="mt-1 text-sm text-muted-foreground">{sectionDescription('memory')}</p>
      </div>
      <label class="grid max-w-sm gap-2">
        <span class="font-sans text-sm font-semibold text-muted-foreground">Max retained messages</span>
        <input
          type="number"
          min="1"
          max="100"
          class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          bind:value={draft.memory.max_messages}
          oninput={markDirty}
        />
      </label>
    </section>
  {/if}
</div>

<Modal
  open={unsaved.unsavedModalOpen}
  title="Discard unsaved preferences?"
  onClose={unsaved.closeUnsavedModalContinueEditing}
>
  <p class="text-sm text-muted-foreground">
    You have unsaved workspace preference changes. Discard them and leave, or keep editing.
  </p>
  {#snippet footer()}
    <Button variant="outline" onclick={unsaved.closeUnsavedModalContinueEditing}>Keep editing</Button>
    <Button variant="destructive" onclick={unsaved.confirmUnsavedModalDiscard}>Discard changes</Button>
  {/snippet}
</Modal>
