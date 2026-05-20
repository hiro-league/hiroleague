<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { BookOpen, KeyRound, Plus, RefreshCw, RotateCcw, Save, Settings2, Trash2 } from '@lucide/svelte';
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
    normalizeWorkspacePreferences,
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
  type ThinkingValue = 'off' | 'minimal' | 'low' | 'medium' | 'high';

  const modalityKeys: ModalityKey[] = ['voice', 'image', 'video', 'file'];
  const modalityLabels: Record<ModalityKey, string> = {
    voice: 'Voice',
    image: 'Image',
    video: 'Video',
    file: 'File'
  };

  const rerankerModelOptions: { id: string; label: string }[] = [
    { id: 'cross-encoder/ms-marco-MiniLM-L-6-v2', label: 'MS MARCO MiniLM L-6 (default)' },
    { id: 'cross-encoder/ms-marco-TinyBERT-L-2-v2', label: 'MS MARCO TinyBERT L-2 (fastest)' },
    { id: 'cross-encoder/ms-marco-electra-base', label: 'MS MARCO ELECTRA base (higher quality)' }
  ];

  const rerankerDeviceOptions: { value: string; label: string }[] = [
    { value: 'auto', label: 'Auto (CUDA if available)' },
    { value: 'cpu', label: 'CPU' },
    { value: 'cuda', label: 'CUDA' }
  ];

  let loading = $state(true);
  let busy = $state(false);
  let catalogReloadBusy = $state(false);
  let error = $state<string | null>(null);
  let toast = $state<Toast | null>(null);
  let sections = $state<PreferenceSection[]>([]);
  let baseline = $state<WorkspacePreferences | null>(null);
  let draft = $state<WorkspacePreferences | null>(null);
  let forceClean = $state(false);

  let chatOptions = $state<CatalogModelRow[]>([]);
  let sttOptions = $state<CatalogModelRow[]>([]);
  let ttsOptions = $state<CatalogModelRow[]>([]);
  let memoryLlmOptions = $state<CatalogModelRow[]>([]);
  let embeddingOptions = $state<CatalogModelRow[]>([]);
  let catalogAllProviders = $state<CatalogProviderRow[]>([]);
  let activeProviders = $state<ActiveProviderRow[]>([]);
  let workspaceActiveProvidersResolved = $state(false);

  const dirty = $derived.by(() => {
    if (forceClean || !baseline || !draft) return false;
    return JSON.stringify(baseline) !== JSON.stringify(draft);
  });

  const canSave = $derived(dirty && !busy && !loading);
  const profileEntries = $derived.by(() =>
    Object.entries(draft?.tuning_profiles ?? {}).sort(([, a], [, b]) =>
      a.label.localeCompare(b.label)
    )
  );

  const chatActiveProviderIds = $derived(
    new Set(activeProviders.filter((row) => row.has_chat).map((row) => row.provider_id))
  );
  const sttActiveProviderIds = $derived(
    new Set(activeProviders.filter((row) => row.has_stt).map((row) => row.provider_id))
  );
  const ttsActiveProviderIds = $derived(
    new Set(activeProviders.filter((row) => row.has_tts).map((row) => row.provider_id))
  );
  const embeddingActiveProviderIds = $derived(
    new Set(activeProviders.filter((row) => row.has_embedding).map((row) => row.provider_id))
  );

  const memoryRerankerEnabled = $derived(Boolean(draft?.memory.reranker.enabled));

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
    const normalized = normalizeWorkspacePreferences(prefs);
    baseline = clonePrefs(normalized);
    draft = clonePrefs(normalized);
    forceClean = false;
  }

  function rerankerDeviceValue(device: string | null | undefined): string {
    if (!device) return 'auto';
    return device;
  }

  function setRerankerDevice(value: string) {
    if (!draft) return;
    draft.memory.reranker.device = value === 'auto' ? null : value;
    markDirty();
  }

  function setRerankerEnabled(enabled: boolean) {
    if (!draft) return;
    draft.memory.reranker.enabled = enabled;
    if (!enabled) draft.memory.search.rerank = false;
    markDirty();
  }

  function setRerankerModel(modelId: string) {
    if (!draft) return;
    draft.memory.reranker.model = modelId;
    markDirty();
  }

  /** Deep-link target for tuning profile editor (character edit → preferences). */
  const tuningProfilesAnchorId = 'preferences-tuning-profiles';

  type PreferencePageSectionId =
    | 'preferences-models'
    | 'preferences-media'
    | 'preferences-memory'
    | typeof tuningProfilesAnchorId;

  const preferenceSectionNav: { id: PreferencePageSectionId; label: string }[] = [
    { id: 'preferences-models', label: 'Models' },
    { id: 'preferences-media', label: 'Media' },
    { id: 'preferences-memory', label: 'Agent Memory' },
    { id: tuningProfilesAnchorId, label: 'Tuning profiles' }
  ];

  let activeSectionId = $state<PreferencePageSectionId>('preferences-models');
  let tuningProfilesHashScrolled = $state(false);

  function sectionNavLinkClass(sectionId: PreferencePageSectionId): string {
    const base =
      'inline-flex h-8 items-center rounded-md border px-3 font-sans text-xs font-semibold transition-colors';
    if (activeSectionId === sectionId) {
      return `${base} border-primary bg-primary/10 text-foreground ring-1 ring-primary/30`;
    }
    return `${base} border-input bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground`;
  }

  /** Sticky shell header (4rem) + preferences section nav — section tops above this line are "passed". */
  const sectionScrollMarkerPx = 128;

  function updateActiveSectionFromScroll() {
    let next: PreferencePageSectionId = preferenceSectionNav[0].id;
    for (const { id } of preferenceSectionNav) {
      const el = document.getElementById(id);
      if (!el) continue;
      if (el.getBoundingClientRect().top <= sectionScrollMarkerPx) {
        next = id;
      }
    }
    if (next !== activeSectionId) activeSectionId = next;
  }

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [prefsPayload, chatPayload, sttPayload, ttsPayload, embeddingPayload, providersPayload] =
        await Promise.all([
          getPreferences(),
          listCatalogModels({ model_kind: 'chat' }),
          listCatalogModels({ model_kind: 'stt' }),
          listCatalogModels({ model_kind: 'tts' }),
          listCatalogModels({ model_kind: 'embedding' }),
          listCatalogProviders()
        ]);
      sections = prefsPayload.data.sections ?? [];
      setDraft(prefsPayload.data.preferences);
      chatOptions = prefsPayload.data.preferences.llm.default_chat
        ? includeUnknownModel(chatPayload.data.models, prefsPayload.data.preferences.llm.default_chat, 'chat')
        : chatPayload.data.models;
      sttOptions = prefsPayload.data.preferences.llm.default_stt
        ? includeUnknownModel(sttPayload.data.models, prefsPayload.data.preferences.llm.default_stt, 'stt')
        : sttPayload.data.models;
      ttsOptions = prefsPayload.data.preferences.llm.default_tts
        ? includeUnknownModel(ttsPayload.data.models, prefsPayload.data.preferences.llm.default_tts, 'tts')
        : ttsPayload.data.models;
      memoryLlmOptions = prefsPayload.data.preferences.memory.default_llm
        ? includeUnknownModel(
            chatPayload.data.models,
            prefsPayload.data.preferences.memory.default_llm,
            'chat'
          )
        : chatPayload.data.models;
      embeddingOptions = prefsPayload.data.preferences.memory.default_embedding_model
        ? includeUnknownModel(
            embeddingPayload.data.models,
            prefsPayload.data.preferences.memory.default_embedding_model,
            'embedding'
          )
        : embeddingPayload.data.models;
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

  function includeUnknownModel(
    models: CatalogModelRow[],
    id: string,
    modelKind: CatalogModelRow['model_kind']
  ): CatalogModelRow[] {
    if (models.some((model) => model.id === id)) return models;
    const [providerId = 'unknown'] = id.split(':', 1);
    return [
      ...models,
      {
        id,
        provider_id: providerId || 'unknown',
        display_name: id,
        model_kind: modelKind
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

  function setMemoryModel(path: 'default_llm' | 'default_embedding_model', id: string | null) {
    if (!draft) return;
    draft.memory[path] = id;
    draft.memory.enabled = Boolean(draft.memory.default_llm && draft.memory.default_embedding_model);
    markDirty();
  }

  function setDefaultTuningProfile(scope: 'llm' | 'memory', id: string) {
    if (!draft || !draft.tuning_profiles[id]) return;
    if (scope === 'llm') draft.llm.default_tuning_profile = id;
    else draft.memory.default_tuning_profile = id;
    markDirty();
  }

  function updateProfile(
    id: string,
    field: 'label' | 'temperature' | 'max_tokens' | 'thinking',
    value: string
  ) {
    if (!draft || !draft.tuning_profiles[id]) return;
    const profile = draft.tuning_profiles[id];
    if (field === 'label') profile.label = value;
    if (field === 'temperature') profile.temperature = Number(value);
    if (field === 'max_tokens') profile.max_tokens = Number(value);
    if (field === 'thinking') profile.thinking = value === 'default' ? null : (value as ThinkingValue);
    markDirty();
  }

  function createProfile() {
    if (!draft) return;
    let index = Object.keys(draft.tuning_profiles).length + 1;
    let id = `custom_${index}`;
    while (draft.tuning_profiles[id]) {
      index += 1;
      id = `custom_${index}`;
    }
    draft.tuning_profiles[id] = {
      label: `Custom ${index}`,
      locked: false,
      temperature: 0.7,
      max_tokens: 2048,
      thinking: null
    };
    markDirty();
  }

  function deleteProfile(id: string) {
    if (!draft) return;
    const profile = draft.tuning_profiles[id];
    if (!profile || profile.locked) return;
    delete draft.tuning_profiles[id];
    if (draft.llm.default_tuning_profile === id) draft.llm.default_tuning_profile = 'balanced_chat';
    if (draft.memory.default_tuning_profile === id) {
      draft.memory.default_tuning_profile = 'memory_extraction';
    }
    markDirty();
  }

  function resetLockedProfile(id: string) {
    if (!draft) return;
    if (id === 'balanced_chat') {
      draft.tuning_profiles[id] = {
        label: 'Balanced chat',
        locked: true,
        temperature: 0.7,
        max_tokens: 2048,
        thinking: null
      };
    } else if (id === 'memory_extraction') {
      draft.tuning_profiles[id] = {
        label: 'Memory extraction',
        locked: true,
        temperature: 0,
        max_tokens: 8192,
        thinking: 'low'
      };
    }
    markDirty();
  }

  function editsForSave(): Record<string, unknown> {
    if (!baseline || !draft) return {};
    const edits: Record<string, unknown> = {};
    const add = (path: string, before: unknown, after: unknown) => {
      if (JSON.stringify(before) !== JSON.stringify(after)) edits[path] = after;
    };
    add('llm.default_chat', baseline.llm.default_chat, draft.llm.default_chat || null);
    add('llm.default_stt', baseline.llm.default_stt, draft.llm.default_stt || null);
    add('llm.default_tts', baseline.llm.default_tts, draft.llm.default_tts || null);
    add(
      'llm.default_tuning_profile',
      baseline.llm.default_tuning_profile,
      draft.llm.default_tuning_profile
    );
    add('memory.default_llm', baseline.memory.default_llm, draft.memory.default_llm || null);
    add(
      'memory.default_embedding_model',
      baseline.memory.default_embedding_model,
      draft.memory.default_embedding_model || null
    );
    add(
      'memory.enabled',
      baseline.memory.enabled,
      Boolean(draft.memory.default_llm && draft.memory.default_embedding_model)
    );
    add(
      'memory.default_tuning_profile',
      baseline.memory.default_tuning_profile,
      draft.memory.default_tuning_profile
    );
    for (const key of modalityKeys) {
      add(`media.input.${key}`, baseline.media.input[key], draft.media.input[key]);
      add(`media.output.${key}`, baseline.media.output[key], draft.media.output[key]);
    }
    add('memory.max_messages', baseline.memory.max_messages, draft.memory.max_messages);
    add('memory.search.top_k', baseline.memory.search.top_k, draft.memory.search.top_k);
    add('memory.search.threshold', baseline.memory.search.threshold, draft.memory.search.threshold);
    add('memory.search.rerank', baseline.memory.search.rerank, draft.memory.search.rerank);
    add('memory.reranker.enabled', baseline.memory.reranker.enabled, draft.memory.reranker.enabled);
    add('memory.reranker.model', baseline.memory.reranker.model, draft.memory.reranker.model);
    add('memory.reranker.device', baseline.memory.reranker.device, draft.memory.reranker.device);
    add('memory.reranker.batch_size', baseline.memory.reranker.batch_size, draft.memory.reranker.batch_size);
    add('tuning_profiles', baseline.tuning_profiles, draft.tuning_profiles);
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
    forceClean = false;
  }

  async function reloadCatalogForPage() {
    catalogReloadBusy = true;
    try {
      const payload = await reloadModelCatalog();
      const [chatPayload, sttPayload, ttsPayload, embeddingPayload, providersPayload] = await Promise.all([
        listCatalogModels({ model_kind: 'chat' }),
        listCatalogModels({ model_kind: 'stt' }),
        listCatalogModels({ model_kind: 'tts' }),
        listCatalogModels({ model_kind: 'embedding' }),
        listCatalogProviders()
      ]);
      chatOptions = chatPayload.data.models;
      sttOptions = sttPayload.data.models;
      ttsOptions = ttsPayload.data.models;
      memoryLlmOptions = chatPayload.data.models;
      embeddingOptions = embeddingPayload.data.models;
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

  $effect(() => {
    if (loading || error || !draft || tuningProfilesHashScrolled) return;
    const hash = window.location.hash.slice(1);
    if (!hash) return;
    const match = preferenceSectionNav.find((section) => section.id === hash);
    if (!match) return;
    tuningProfilesHashScrolled = true;
    activeSectionId = match.id;
    requestAnimationFrame(() => {
      document.getElementById(match.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  $effect(() => {
    if (loading || error || !draft) return;

    let rafId = 0;
    let cancelled = false;

    const scheduleUpdate = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        if (!cancelled) updateActiveSectionFromScroll();
      });
    };

    void tick().then(() => {
      if (cancelled) return;
      updateActiveSectionFromScroll();
      window.addEventListener('scroll', scheduleUpdate, { passive: true });
      window.addEventListener('resize', scheduleUpdate, { passive: true });
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafId);
      window.removeEventListener('scroll', scheduleUpdate);
      window.removeEventListener('resize', scheduleUpdate);
    };
  });

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
      {#each preferenceSectionNav as section (section.id)}
        <a
          class={sectionNavLinkClass(section.id)}
          href={`#${section.id}`}
          aria-current={activeSectionId === section.id ? 'location' : undefined}
          onclick={() => {
            activeSectionId = section.id;
          }}
        >
          {section.label}
        </a>
      {/each}
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
      <label class="grid max-w-md gap-2">
        <span class="font-sans text-sm font-semibold text-muted-foreground">Default chat tuning profile</span>
        <select
          class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          value={draft.llm.default_tuning_profile}
          onchange={(event) => setDefaultTuningProfile('llm', event.currentTarget.value)}
        >
          {#each profileEntries as [id, profile] (id)}
            <option value={id}>{profile.label}</option>
          {/each}
        </select>
      </label>

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

    <section id="preferences-memory" class="scroll-mt-32 grid gap-4 border-b pb-6">
      <div>
        <h3 class="font-sans text-xl font-semibold text-foreground">
          {sectionLabel('memory', 'Agent Memory')}
        </h3>
        <p class="mt-1 text-sm text-muted-foreground">{sectionDescription('memory')}</p>
      </div>
      <SingleModelPicker
        label="Memory LLM model"
        hint="Used by the memory service for memory extraction."
        selectedId={draft.memory.default_llm}
        catalogModels={memoryLlmOptions}
        {catalogAllProviders}
        {workspaceActiveProvidersResolved}
        workspaceActiveProviderIds={chatActiveProviderIds}
        {busy}
        emptyProviders="No chat providers in catalog."
        emptyModelsForProvider="No chat models for this provider."
        onSelect={(id) => setMemoryModel('default_llm', id)}
        onChange={markDirty}
      />
      <SingleModelPicker
        label="Memory embedding model"
        hint="Used by the memory service for vector search."
        selectedId={draft.memory.default_embedding_model}
        catalogModels={embeddingOptions}
        {catalogAllProviders}
        {workspaceActiveProvidersResolved}
        workspaceActiveProviderIds={embeddingActiveProviderIds}
        {busy}
        emptyProviders="No embedding providers in catalog."
        emptyModelsForProvider="No embedding models for this provider."
        onSelect={(id) => setMemoryModel('default_embedding_model', id)}
        onChange={markDirty}
      />
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
      <label class="grid max-w-md gap-2">
        <span class="font-sans text-sm font-semibold text-muted-foreground">Default memory tuning profile</span>
        <select
          class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          value={draft.memory.default_tuning_profile}
          onchange={(event) => setDefaultTuningProfile('memory', event.currentTarget.value)}
        >
          {#each profileEntries as [id, profile] (id)}
            <option value={id}>{profile.label}</option>
          {/each}
        </select>
      </label>

      <div class="grid gap-3 rounded-md border border-border/70 bg-background/45 p-4">
        <div>
          <h4 class="font-sans text-base font-semibold text-foreground">Local reranker</h4>
          <p class="mt-1 text-sm text-muted-foreground">
            Optional cross-encoder reranking (sentence-transformers). Downloads the model on first use.
            Rebuilds the memory service when saved.
          </p>
        </div>
        <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
          <input
            type="checkbox"
            checked={draft.memory.reranker.enabled}
            disabled={busy}
            onchange={(event) => setRerankerEnabled(event.currentTarget.checked)}
          />
          <span class="font-sans text-sm font-medium">Enable local reranker</span>
        </label>
        <div class="grid gap-3 md:grid-cols-2">
          <label class="grid gap-1.5">
            <span class="font-sans text-xs font-semibold text-muted-foreground">Cross-encoder model</span>
            <select
              class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              value={draft.memory.reranker.model}
              disabled={busy || !memoryRerankerEnabled}
              onchange={(event) => setRerankerModel(event.currentTarget.value)}
            >
              {#each rerankerModelOptions as option (option.id)}
                <option value={option.id}>{option.label}</option>
              {/each}
            </select>
          </label>
          <label class="grid gap-1.5">
            <span class="font-sans text-xs font-semibold text-muted-foreground">Device</span>
            <select
              class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              value={rerankerDeviceValue(draft.memory.reranker.device)}
              disabled={busy || !memoryRerankerEnabled}
              onchange={(event) => setRerankerDevice(event.currentTarget.value)}
            >
              {#each rerankerDeviceOptions as option (option.value)}
                <option value={option.value}>{option.label}</option>
              {/each}
            </select>
          </label>
        </div>
        <label class="grid max-w-sm gap-1.5">
          <span class="font-sans text-xs font-semibold text-muted-foreground">Batch size</span>
          <input
            type="number"
            min="1"
            max="512"
            step="1"
            class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            bind:value={draft.memory.reranker.batch_size}
            disabled={busy || !memoryRerankerEnabled}
            oninput={markDirty}
          />
        </label>
      </div>

      <div class="grid gap-3 rounded-md border border-border/70 bg-background/45 p-4">
        <div>
          <h4 class="font-sans text-base font-semibold text-foreground">Retrieval</h4>
          <p class="mt-1 text-sm text-muted-foreground">
            Controls long-term memory search before each reply (memory_in). Rebuilds the memory service when saved.
          </p>
        </div>
        <div class="grid gap-3 md:grid-cols-2">
          <label class="grid gap-1.5">
            <span class="font-sans text-xs font-semibold text-muted-foreground">Results per search</span>
            <input
              type="number"
              min="1"
              max="100"
              step="1"
              class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              bind:value={draft.memory.search.top_k}
              disabled={busy}
              oninput={markDirty}
            />
          </label>
          <label class="grid gap-1.5">
            <span class="font-sans text-xs font-semibold text-muted-foreground">Minimum relevance</span>
            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              bind:value={draft.memory.search.threshold}
              disabled={busy}
              oninput={markDirty}
            />
            <span class="text-xs text-muted-foreground">Score 0–1; use 0 to disable filtering.</span>
          </label>
        </div>
        <label
          class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3 {!memoryRerankerEnabled
            ? 'opacity-50'
            : ''}"
        >
          <input
            type="checkbox"
            bind:checked={draft.memory.search.rerank}
            disabled={busy || !memoryRerankerEnabled}
            onchange={markDirty}
          />
          <span class="font-sans text-sm font-medium">Rerank search results</span>
        </label>
        {#if !memoryRerankerEnabled}
          <p class="text-xs text-muted-foreground">Enable the local reranker above to use reranking.</p>
        {/if}
      </div>
    </section>

    <section id={tuningProfilesAnchorId} class="scroll-mt-32 grid gap-4">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 class="font-sans text-xl font-semibold text-foreground">Tuning profiles</h3>
          <p class="mt-1 text-sm text-muted-foreground">
            Temperature, max tokens, and thinking presets referenced by the chat and memory defaults above.
          </p>
        </div>
        <Button variant="outline" size="sm" disabled={busy} onclick={createProfile}>
          <Plus size={14} /> Add profile
        </Button>
      </div>
      <div class="grid gap-3 rounded-md border border-border/70 bg-background/45 p-4">
        <div class="grid gap-3">
          {#each profileEntries as [id, profile] (id)}
            <div class="grid gap-3 rounded-md border border-border/60 bg-card/45 p-3">
              <div class="flex flex-col gap-2 sm:flex-row sm:items-end">
                <label class="grid flex-1 gap-1.5">
                  <span class="font-sans text-xs font-semibold text-muted-foreground">Name</span>
                  <input
                    class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    value={profile.label}
                    oninput={(event) => updateProfile(id, 'label', event.currentTarget.value)}
                  />
                </label>
                <div class="flex gap-2">
                  {#if profile.locked}
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onclick={() => resetLockedProfile(id)}
                    >
                      <RotateCcw size={14} /> Reset
                    </Button>
                  {:else}
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={busy}
                      onclick={() => deleteProfile(id)}
                    >
                      <Trash2 size={14} /> Delete
                    </Button>
                  {/if}
                </div>
              </div>
              <div class="grid gap-3 md:grid-cols-3">
                <label class="grid gap-1.5">
                  <span class="font-sans text-xs font-semibold text-muted-foreground">Temperature</span>
                  <input
                    type="number"
                    min="0"
                    max="2"
                    step="0.1"
                    class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    value={profile.temperature}
                    oninput={(event) => updateProfile(id, 'temperature', event.currentTarget.value)}
                  />
                </label>
                <label class="grid gap-1.5">
                  <span class="font-sans text-xs font-semibold text-muted-foreground">Max tokens</span>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    value={profile.max_tokens}
                    oninput={(event) => updateProfile(id, 'max_tokens', event.currentTarget.value)}
                  />
                </label>
                <label class="grid gap-1.5">
                  <span class="font-sans text-xs font-semibold text-muted-foreground">Thinking</span>
                  <select
                    class="h-10 rounded-md border border-input bg-background px-3 font-sans text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    value={profile.thinking ?? 'default'}
                    onchange={(event) => updateProfile(id, 'thinking', event.currentTarget.value)}
                  >
                    <option value="default">Model default</option>
                    <option value="off">Off</option>
                    <option value="minimal">Minimal</option>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
              </div>
            </div>
          {/each}
        </div>
      </div>
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
