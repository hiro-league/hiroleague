<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { FilterX, KeyRound, RefreshCw, Search, Trash2 } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Modal from '$lib/ui/Modal.svelte';
  import {
    addProviderApiKey,
    listCatalogModels,
    listCatalogProviders,
    listActiveProviders,
    listAddableProviders,
    removeProvider,
    scanProviderEnvironment,
    type ActiveProviderRow,
    type AddableProviderRow,
    type CatalogModelRow,
    type CatalogProviderRow
  } from '$lib/api/catalog';
  import { createCatalogPreferences } from '$lib/preferences/catalog-preferences.svelte';
  import { cn } from '$lib/utils';

  const prefs = createCatalogPreferences();
  const modelKindOptions = ['', 'chat', 'tts', 'stt', 'embedding', 'image_gen'];
  const modelClassOptions = ['', 'agentic', 'fast', 'balanced', 'reasoning', 'creative', 'coding'];
  const hostingOptions = ['', 'cloud', 'local'];

  let providers = $state<CatalogProviderRow[]>([]);
  let models = $state<CatalogModelRow[]>([]);
  let activeProviders = $state<ActiveProviderRow[]>([]);
  let addableProviders = $state<AddableProviderRow[]>([]);
  let catalogVersion = $state<number | null>(null);
  let providersLoading = $state(true);
  let modelsLoading = $state(false);
  let activeProvidersLoading = $state(false);
  let addableProvidersLoading = $state(false);
  let activeProvidersBusy = $state(false);
  let providersError = $state<string | null>(null);
  let modelsError = $state<string | null>(null);
  let activeProvidersError = $state<string | null>(null);
  let providerDialog = $state<'add' | 'remove' | null>(null);
  let selectedActiveProvider = $state<ActiveProviderRow | null>(null);
  let toast = $state<{ kind: 'success' | 'error' | 'info' | 'warning'; message: string } | null>(
    null
  );
  let addProviderForm = $state({
    provider_id: '',
    api_key: ''
  });
  let modelFilters = $state({
    provider_id: '',
    model_kind: '',
    model_class: '',
    hosting: ''
  });

  const providerLabels = $derived(
    providers.reduce<Record<string, string>>((acc, provider) => {
      acc[provider.id] = `${provider.display_name} (${provider.id})`;
      return acc;
    }, {})
  );

  const providerCounts = $derived(
    providers.reduce(
      (acc, provider) => {
        acc.total += 1;
        if (provider.hosting === 'cloud') acc.cloud += 1;
        if (provider.hosting === 'local') acc.local += 1;
        return acc;
      },
      { total: 0, cloud: 0, local: 0 }
    )
  );

  const activeProviderCounts = $derived(
    activeProviders.reduce(
      (acc, provider) => {
        acc.total += 1;
        if (provider.hosting === 'cloud') acc.cloud += 1;
        if (provider.hosting === 'local') acc.local += 1;
        return acc;
      },
      { total: 0, cloud: 0, local: 0 }
    )
  );

  function notify(kind: 'success' | 'error' | 'info' | 'warning', message: string) {
    toast = { kind, message };
    window.setTimeout(() => {
      toast = null;
    }, 4500);
  }

  function initializeFiltersFromUrl() {
    modelFilters = {
      provider_id: page.url.searchParams.get('provider_id') ?? '',
      model_kind: page.url.searchParams.get('model_kind') ?? '',
      model_class: page.url.searchParams.get('model_class') ?? '',
      hosting: page.url.searchParams.get('hosting') ?? ''
    };
  }

  async function loadProviders() {
    providersLoading = true;
    providersError = null;
    try {
      const payload = await listCatalogProviders();
      providers = payload.data;
    } catch (err) {
      providersError = err instanceof Error ? err.message : 'Failed to load catalog providers.';
      providers = [];
    } finally {
      providersLoading = false;
    }
  }

  async function loadModels() {
    modelsLoading = true;
    modelsError = null;
    try {
      const payload = await listCatalogModels(modelFilters);
      catalogVersion = payload.data.catalog_version;
      models = payload.data.models;
    } catch (err) {
      modelsError = err instanceof Error ? err.message : 'Failed to load catalog models.';
      models = [];
    } finally {
      modelsLoading = false;
    }
  }

  async function loadActiveProviders() {
    activeProvidersLoading = true;
    activeProvidersError = null;
    try {
      const payload = await listActiveProviders();
      activeProviders = payload.data;
    } catch (err) {
      activeProvidersError =
        err instanceof Error ? err.message : 'Failed to load active providers.';
      activeProviders = [];
    } finally {
      activeProvidersLoading = false;
    }
  }

  async function switchTab(tab: 'providers' | 'models') {
    await prefs.setActiveTab(tab, tab === 'models' ? modelFilters : {});
    if (tab === 'models' && models.length === 0 && !modelsLoading) {
      await loadModels();
    }
  }

  async function openModelsForProvider(providerId: string) {
    modelFilters = { ...modelFilters, provider_id: providerId };
    await prefs.setActiveTab('models', modelFilters);
    await loadModels();
  }

  async function applyModelFilters() {
    await prefs.setActiveTab('models', modelFilters);
    await loadModels();
  }

  async function clearModelFilters() {
    modelFilters = {
      provider_id: '',
      model_kind: '',
      model_class: '',
      hosting: ''
    };
    await prefs.setActiveTab('models');
    await loadModels();
  }

  function activeProviderKinds(provider: ActiveProviderRow) {
    const kinds = [];
    if (provider.has_chat) kinds.push('chat');
    if (provider.has_tts) kinds.push('tts');
    if (provider.has_stt) kinds.push('stt');
    return kinds.length ? kinds.join(', ') : '-';
  }

  function closeProviderDialog() {
    if (activeProvidersBusy) return;
    providerDialog = null;
    selectedActiveProvider = null;
  }

  async function openAddProviderDialog() {
    activeProvidersBusy = true;
    addableProvidersLoading = true;
    try {
      const payload = await listAddableProviders();
      addableProviders = payload.data;
      addProviderForm = {
        provider_id: addableProviders[0]?.id ?? '',
        api_key: ''
      };
      if (addableProviders.length === 0) {
        notify('info', 'All cloud catalog providers are already configured.');
        return;
      }
      providerDialog = 'add';
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to list addable providers.');
    } finally {
      activeProvidersBusy = false;
      addableProvidersLoading = false;
    }
  }

  async function submitAddProvider() {
    activeProvidersBusy = true;
    try {
      await addProviderApiKey(addProviderForm.provider_id, addProviderForm.api_key);
      notify('success', `Stored API key for ${addProviderForm.provider_id}.`);
      providerDialog = null;
      await loadActiveProviders();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to store API key.');
    } finally {
      activeProvidersBusy = false;
    }
  }

  async function scanEnvironment() {
    activeProvidersBusy = true;
    try {
      const payload = await scanProviderEnvironment();
      const count = payload.data;
      notify(
        count > 0 ? 'success' : 'info',
        count > 0
          ? `Imported ${count} provider key${count === 1 ? '' : 's'} from the environment.`
          : 'No new keys imported.'
      );
      await loadActiveProviders();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Environment scan failed.');
    } finally {
      activeProvidersBusy = false;
    }
  }

  function openRemoveProviderDialog(provider: ActiveProviderRow) {
    selectedActiveProvider = provider;
    providerDialog = 'remove';
  }

  async function submitRemoveProvider() {
    if (!selectedActiveProvider) return;
    activeProvidersBusy = true;
    try {
      const payload = await removeProvider(selectedActiveProvider.provider_id);
      notify(
        payload.data ? 'success' : 'warning',
        payload.data
          ? `Removed credentials for ${selectedActiveProvider.provider_id}.`
          : 'Provider was not configured.'
      );
      providerDialog = null;
      selectedActiveProvider = null;
      await loadActiveProviders();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Remove provider failed.');
    } finally {
      activeProvidersBusy = false;
    }
  }

  function modelPricing(model: CatalogModelRow) {
    const pricing = model.pricing;
    if (!pricing || typeof pricing !== 'object') return '-';

    const num = (key: string) => {
      const raw = pricing[key];
      const value = typeof raw === 'number' ? raw : Number(raw);
      return Number.isFinite(value) ? value : null;
    };

    if (model.model_kind === 'chat') {
      const input = num('input_per_1m_tokens');
      const output = num('output_per_1m_tokens');
      if (input !== null || output !== null) {
        return [
          input !== null ? `$${input.toFixed(2)}/1M in` : '',
          output !== null ? `$${output.toFixed(2)}/1M out` : ''
        ]
          .filter(Boolean)
          .join(' / ');
      }
    }
    if (model.model_kind === 'embedding') {
      const input = num('input_per_1m_tokens');
      if (input !== null) return `$${input.toFixed(2)}/1M tokens`;
    }
    if (model.model_kind === 'tts') {
      const perCharacter = num('per_character');
      if (perCharacter !== null) return `$${(perCharacter * 1000).toFixed(4)}/1K chars`;
    }
    if (model.model_kind === 'stt') {
      const perSecond = num('per_second');
      if (perSecond !== null) return `$${perSecond.toFixed(4)}/sec audio`;
    }
    return '-';
  }

  function listText(values: string[] | undefined) {
    return values?.length ? values.slice().sort().join(', ') : '-';
  }

  onMount(async () => {
    prefs.initialize();
    initializeFiltersFromUrl();
    await loadProviders();
    if (prefs.activeTab === 'models') {
      await loadModels();
    }
  });
</script>

<section class="grid max-w-[1420px] gap-5">
  <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">AI Models</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Model Catalog</h2>
    </div>
    <div class="inline-flex rounded-lg border bg-card p-1" role="tablist" aria-label="Catalog sections">
      <Button
        class={cn(
          'shadow-none',
          prefs.activeTab === 'providers' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={prefs.activeTab === 'providers' ? 'secondary' : 'ghost'}
        role="tab"
        aria-selected={prefs.activeTab === 'providers'}
        onclick={() => switchTab('providers')}
      >
        Catalog providers
      </Button>
      <Button
        class={cn(
          'shadow-none',
          prefs.activeTab === 'models' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={prefs.activeTab === 'models' ? 'secondary' : 'ghost'}
        role="tab"
        aria-selected={prefs.activeTab === 'models'}
        onclick={() => switchTab('models')}
      >
        Models
      </Button>
    </div>
  </div>

  {#if toast}
    <div
      class={cn(
        'w-fit max-w-full rounded-md border px-3 py-2 font-sans text-sm font-semibold',
        toast.kind === 'success' && 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
        toast.kind === 'error' && 'border-destructive/30 bg-destructive/10 text-destructive',
        toast.kind === 'warning' && 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
        toast.kind === 'info' && 'border-primary/30 bg-primary/10 text-primary'
      )}
    >
      {toast.message}
    </div>
  {/if}

  {#if prefs.activeTab === 'providers'}
    <section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="text-lg font-semibold">Catalog providers</h3>
          <span class="font-sans text-sm text-muted-foreground">
            {providerCounts.total} providers / {providerCounts.cloud} cloud / {providerCounts.local} local
          </span>
        </div>
        <Button variant="outline" onclick={loadProviders}><RefreshCw size={15} /> Refresh</Button>
      </div>

      {#if providersLoading}
        <p class="text-muted-foreground">Loading catalog providers...</p>
      {:else if providersError}
        <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load catalog providers</strong>
          <span class="block text-sm">{providersError}</span>
        </div>
      {:else if providers.length === 0}
        <p class="text-muted-foreground">No providers in the bundled catalog.</p>
      {:else}
        <div class="overflow-x-auto rounded-md border">
          <div class="min-w-[980px]">
            <div class="grid grid-cols-[1.1fr_100px_1fr_1.4fr_120px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground">
              <span>Provider</span>
              <span>Hosting</span>
              <span>Credential env</span>
              <span>Recommended models</span>
              <span>Updated</span>
            </div>
            {#each providers as provider}
              <div class="grid min-h-16 grid-cols-[1.1fr_100px_1fr_1.4fr_120px] gap-3 border-t px-3 py-3">
                <span class="min-w-0">
                  <button
                    class="block max-w-full truncate font-sans text-sm font-semibold text-primary hover:underline"
                    type="button"
                    onclick={() => openModelsForProvider(provider.id)}
                    title={`View models for ${provider.display_name}`}
                  >
                    {provider.display_name}
                  </button>
                  <small class="block truncate text-xs text-muted-foreground">{provider.id}</small>
                </span>
                <span><Badge variant={provider.hosting === 'cloud' ? 'secondary' : 'outline'}>{provider.hosting}</Badge></span>
                <span class="truncate text-xs text-muted-foreground">
                  {provider.credential_env_keys?.length ? provider.credential_env_keys.join(', ') : '-'}
                </span>
                <span class="min-w-0 text-xs text-muted-foreground">
                  {#if provider.recommended_models}
                    {Object.entries(provider.recommended_models).map(([kind, model]) => `${kind}: ${model}`).join(' / ')}
                  {:else}
                    -
                  {/if}
                </span>
                <span class="text-xs text-muted-foreground">{provider.metadata_updated_at ?? '-'}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  {:else if prefs.activeTab === 'models'}
    <section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="text-lg font-semibold">Models</h3>
          <span class="font-sans text-sm text-muted-foreground">
            {models.length} shown{catalogVersion ? ` / catalog version ${catalogVersion}` : ''}
          </span>
        </div>
        <Button variant="outline" onclick={loadModels}><RefreshCw size={15} /> Refresh</Button>
      </div>

      <div class="grid gap-3 md:grid-cols-5">
        <label class="grid gap-1 font-sans text-xs font-semibold text-muted-foreground">
          Provider
          <select class="h-9 rounded-md border bg-background px-2 text-sm text-foreground" bind:value={modelFilters.provider_id} onchange={applyModelFilters}>
            <option value="">All providers</option>
            {#each providers as provider}
              <option value={provider.id}>{provider.display_name} ({provider.id})</option>
            {/each}
          </select>
        </label>
        <label class="grid gap-1 font-sans text-xs font-semibold text-muted-foreground">
          Kind
          <select class="h-9 rounded-md border bg-background px-2 text-sm text-foreground" bind:value={modelFilters.model_kind} onchange={applyModelFilters}>
            {#each modelKindOptions as option}
              <option value={option}>{option || 'All kinds'}</option>
            {/each}
          </select>
        </label>
        <label class="grid gap-1 font-sans text-xs font-semibold text-muted-foreground">
          Class
          <select class="h-9 rounded-md border bg-background px-2 text-sm text-foreground" bind:value={modelFilters.model_class} onchange={applyModelFilters}>
            {#each modelClassOptions as option}
              <option value={option}>{option || 'All classes'}</option>
            {/each}
          </select>
        </label>
        <label class="grid gap-1 font-sans text-xs font-semibold text-muted-foreground">
          Hosting
          <select class="h-9 rounded-md border bg-background px-2 text-sm text-foreground" bind:value={modelFilters.hosting} onchange={applyModelFilters}>
            {#each hostingOptions as option}
              <option value={option}>{option || 'All hosting'}</option>
            {/each}
          </select>
        </label>
        <div class="flex items-end">
          <Button class="w-full" variant="outline" onclick={clearModelFilters}><FilterX size={15} /> Clear filters</Button>
        </div>
      </div>

      {#if modelsLoading}
        <p class="text-muted-foreground">Loading models...</p>
      {:else if modelsError}
        <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load models</strong>
          <span class="block text-sm">{modelsError}</span>
        </div>
      {:else if models.length === 0}
        <p class="text-muted-foreground">No models match the current filters.</p>
      {:else}
        <div class="overflow-x-auto rounded-md border">
          <div class="min-w-[1180px]">
            <div class="grid grid-cols-[1fr_1.25fr_90px_110px_100px_100px_1fr_1.35fr] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground">
              <span>Provider</span>
              <span>Model</span>
              <span>Kind</span>
              <span>Class</span>
              <span>Hosting</span>
              <span>Context</span>
              <span>Pricing</span>
              <span>Features</span>
            </div>
            {#each models as model}
              <div class="grid min-h-16 grid-cols-[1fr_1.25fr_90px_110px_100px_100px_1fr_1.35fr] gap-3 border-t px-3 py-3">
                <span class="truncate text-sm">{providerLabels[model.provider_id] ?? model.provider_id}</span>
                <span class="min-w-0">
                  <strong class="block truncate font-sans text-sm">{model.display_name}</strong>
                  <small class="block truncate text-xs text-muted-foreground">{model.id}</small>
                </span>
                <span><Badge variant="outline">{model.model_kind}</Badge></span>
                <span class="truncate text-xs text-muted-foreground">{model.model_class ?? '-'}</span>
                <span class="truncate text-xs text-muted-foreground">{model.hosting ?? '-'}</span>
                <span class="text-right font-sans text-xs text-muted-foreground">
                  {typeof model.context_window === 'number' ? model.context_window.toLocaleString() : '-'}
                </span>
                <span class="text-xs text-muted-foreground">{modelPricing(model)}</span>
                <span class="truncate text-xs text-muted-foreground" title={listText(model.features)}>{listText(model.features)}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  {:else}
    <section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="text-lg font-semibold">Active providers</h3>
          <span class="font-sans text-sm text-muted-foreground">
            {activeProviderCounts.total} configured / {activeProviderCounts.cloud} cloud / {activeProviderCounts.local} local
          </span>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button variant="outline" disabled={activeProvidersBusy} onclick={loadActiveProviders}>
            <RefreshCw size={15} /> Refresh
          </Button>
          <Button variant="outline" disabled={activeProvidersBusy} onclick={scanEnvironment}>
            <Search size={15} /> Scan environment
          </Button>
          <Button disabled={activeProvidersBusy} onclick={openAddProviderDialog}>
            <KeyRound size={15} /> Add API key
          </Button>
        </div>
      </div>

      {#if activeProvidersLoading}
        <p class="text-muted-foreground">Loading active providers...</p>
      {:else if activeProvidersError}
        <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load active providers</strong>
          <span class="block text-sm">{activeProvidersError}</span>
        </div>
      {:else if activeProviders.length === 0}
        <p class="text-muted-foreground">
          No providers configured for this workspace. Add an API key or scan your environment.
        </p>
      {:else}
        <div class="overflow-x-auto rounded-md border">
          <div class="min-w-[900px]">
            <div class="grid grid-cols-[1.2fr_110px_130px_90px_1fr_120px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground">
              <span>Provider</span>
              <span>Hosting</span>
              <span>Auth</span>
              <span>Models</span>
              <span>Kinds</span>
              <span>Actions</span>
            </div>
            {#each activeProviders as provider}
              <div class="grid min-h-16 grid-cols-[1.2fr_110px_130px_90px_1fr_120px] gap-3 border-t px-3 py-3">
                <span class="min-w-0">
                  <strong class="block truncate font-sans text-sm">{provider.display_name}</strong>
                  <small class="block truncate text-xs text-muted-foreground">{provider.provider_id}</small>
                </span>
                <span><Badge variant={provider.hosting === 'cloud' ? 'secondary' : 'outline'}>{provider.hosting}</Badge></span>
                <span class="truncate text-xs text-muted-foreground">{provider.auth_method}</span>
                <span class="text-right font-sans text-xs text-muted-foreground">
                  {provider.available_model_count}
                </span>
                <span class="truncate text-xs text-muted-foreground">{activeProviderKinds(provider)}</span>
                <span>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={activeProvidersBusy}
                    onclick={() => openRemoveProviderDialog(provider)}
                  >
                    <Trash2 size={13} /> Remove
                  </Button>
                </span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  {/if}
</section>

<Modal open={providerDialog === 'add'} title="Add provider API key" onClose={closeProviderDialog}>
  {#if addableProvidersLoading}
    <p class="text-muted-foreground">Loading providers...</p>
  {:else}
    <label>
      Provider
      <select
        class="h-9 rounded-md border border-input bg-background px-3 font-sans text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        bind:value={addProviderForm.provider_id}
      >
        {#each addableProviders as provider}
          <option value={provider.id}>{provider.display_name} ({provider.id})</option>
        {/each}
      </select>
    </label>
    <label>
      API key
      <input type="password" bind:value={addProviderForm.api_key} placeholder="Paste the provider API key" />
    </label>
  {/if}
  {#snippet footer()}
    <Button variant="outline" onclick={closeProviderDialog}>Cancel</Button>
    <Button disabled={activeProvidersBusy || !addProviderForm.provider_id || !addProviderForm.api_key.trim()} onclick={submitAddProvider}>
      Save
    </Button>
  {/snippet}
</Modal>

<Modal
  open={providerDialog === 'remove'}
  title={`Remove provider '${selectedActiveProvider?.provider_id ?? ''}'`}
  subtitle={selectedActiveProvider?.display_name ?? ''}
  onClose={closeProviderDialog}
>
  <p class="text-sm text-muted-foreground">
    This removes stored credentials for the selected workspace. Models from this provider will be unavailable until credentials are added again.
  </p>
  {#snippet footer()}
    <Button variant="outline" onclick={closeProviderDialog}>Cancel</Button>
    <Button variant="destructive" disabled={activeProvidersBusy} onclick={submitRemoveProvider}>Remove</Button>
  {/snippet}
</Modal>
