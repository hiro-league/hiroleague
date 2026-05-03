<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import {
    ArrowUpRight,
    Box,
    Cloud,
    FilterX,
    Image as ImageIcon,
    KeyRound,
    Layers,
    MessageSquare,
    Mic,
    RefreshCw,
    Search,
    Server,
    Trash2,
    Volume2
  } from '@lucide/svelte';
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
    reloadModelCatalog,
    scanProviderEnvironment,
    type ActiveProviderRow,
    type AddableProviderRow,
    type CatalogModelFilters,
    type CatalogModelRow,
    type CatalogProviderRow
  } from '$lib/api/catalog';
  import { createCatalogPreferences } from '$lib/preferences/catalog-preferences.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { cn } from '$lib/utils';

  const prefs = createCatalogPreferences();

  const MODEL_KIND_FILTER_IDS = ['chat', 'tts', 'stt', 'embedding', 'image_gen'] as const;
  type ModelKindFilterId = (typeof MODEL_KIND_FILTER_IDS)[number];

  const MODEL_KIND_FILTER_UI: Record<
    ModelKindFilterId,
    { Icon: typeof MessageSquare; title: string }
  > = {
    chat: { Icon: MessageSquare, title: 'Chat' },
    tts: { Icon: Volume2, title: 'Text-to-speech (TTS)' },
    stt: { Icon: Mic, title: 'Speech-to-text (STT)' },
    embedding: { Icon: Layers, title: 'Embedding' },
    image_gen: { Icon: ImageIcon, title: 'Image generation' }
  };

  function emptyModelKindToggles(): Record<ModelKindFilterId, boolean> {
    return {
      chat: false,
      tts: false,
      stt: false,
      embedding: false,
      image_gen: false
    };
  }

  function modelKindUiForRow(kind: string) {
    const k = kind as ModelKindFilterId;
    if (k in MODEL_KIND_FILTER_UI) {
      return MODEL_KIND_FILTER_UI[k];
    }
    return { Icon: Box, title: kind };
  }

  const HOSTING_FILTER_IDS = ['cloud', 'local'] as const;
  type HostingFilterId = (typeof HOSTING_FILTER_IDS)[number];

  const HOSTING_FILTER_UI: Record<
    HostingFilterId,
    { Icon: typeof Cloud; title: string }
  > = {
    cloud: { Icon: Cloud, title: 'Cloud' },
    local: { Icon: Server, title: 'Local' }
  };

  function emptyHostingToggles(): Record<HostingFilterId, boolean> {
    return { cloud: false, local: false };
  }

  function catalogHostingUiForRow(hosting: string | null | undefined) {
    const h = (hosting ?? '').trim().toLowerCase() as HostingFilterId;
    if (h in HOSTING_FILTER_UI) {
      return HOSTING_FILTER_UI[h];
    }
    return { Icon: Box, title: hosting?.trim() ? hosting : 'Unknown hosting' };
  }

  const modelClassOptions = ['', 'agentic', 'fast', 'balanced', 'reasoning', 'creative', 'coding'];

  let providers = $state<CatalogProviderRow[]>([]);
  let models = $state<CatalogModelRow[]>([]);
  let activeProviders = $state<ActiveProviderRow[]>([]);
  let addableProviders = $state<AddableProviderRow[]>([]);
  let catalogVersion = $state<string | null>(null);
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
    model_class: ''
  });
  let modelKindToggles = $state(emptyModelKindToggles());
  let hostingToggles = $state(emptyHostingToggles());

  /** Query params for the Models tab (shared by filters, URL sync, and navigation). */
  function modelsTabSearchParams(): Record<string, string> {
    const p: Record<string, string> = {};
    const prov = modelFilters.provider_id.trim();
    if (prov) p.provider_id = prov;
    const kinds = MODEL_KIND_FILTER_IDS.filter((k) => modelKindToggles[k]);
    if (kinds.length) p.model_kind = kinds.join(',');
    const mc = modelFilters.model_class.trim();
    if (mc) p.model_class = mc;
    const hostings = HOSTING_FILTER_IDS.filter((h) => hostingToggles[h]);
    if (hostings.length === 1) p.hosting = hostings[0];
    return p;
  }

  function catalogFetchFilters(): CatalogModelFilters {
    const kinds = MODEL_KIND_FILTER_IDS.filter((k) => modelKindToggles[k]);
    const out: CatalogModelFilters = {};
    const prov = modelFilters.provider_id.trim();
    if (prov) out.provider_id = prov;
    if (modelFilters.model_class.trim()) out.model_class = modelFilters.model_class.trim();
    const hostings = HOSTING_FILTER_IDS.filter((h) => hostingToggles[h]);
    if (hostings.length === 1) out.hosting = hostings[0];
    // Single kind: narrow on the server; multiple kinds: fetch without kind and filter client-side.
    if (kinds.length === 1) out.model_kind = kinds[0];
    return out;
  }

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

  /** Canonical ids listed under any provider's `recommended_models` in the bundled catalog. */
  const recommendedCatalogModelIds = $derived(
    new Set(
      providers.flatMap((p) =>
        p.recommended_models ? Object.values(p.recommended_models).filter(Boolean) : []
      )
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

  let catalogReloadBusy = $state(false);

  function notify(kind: 'success' | 'error' | 'info' | 'warning', message: string) {
    toast = { kind, message };
    window.setTimeout(() => {
      toast = null;
    }, 4500);
  }

  /** TTS catalog table: $/1K input characters (script length), not tokens. */
  function formatTtsUsdPer1k(usd: number): string {
    if (!Number.isFinite(usd)) return '';
    return `$${usd.toFixed(3)}/1K characters`;
  }

  /** Read first numeric pricing field (handles camelCase if any proxy rewrites keys). */
  function pricingNum(pricing: Record<string, unknown>, ...keys: string[]): number | null {
    for (const key of keys) {
      const raw = pricing[key];
      if (raw === undefined || raw === null) continue;
      const value = typeof raw === 'number' ? raw : Number(raw);
      if (Number.isFinite(value)) return value;
    }
    return null;
  }

  /**
   * USD per ~1k chars of script → speech for the catalog table.
   * Prefer catalog `estimated_usd_per_1k_chars_speech`; if missing (e.g. HiroServer not restarted after
   * PricingBlock schema change), derive from the same token assumptions as catalog.yaml.
   */
  function ttsUsdPer1kCatalogEstimate(model: CatalogModelRow, pricing: Record<string, unknown>): number | null {
    const est = pricingNum(
      pricing,
      'estimated_usd_per_1k_chars_speech',
      'estimatedUsdPer1kCharsSpeech'
    );
    if (est !== null && est >= 0) return est;

    const input = pricingNum(pricing, 'input_per_1m_tokens');
    const output = pricingNum(pricing, 'output_per_1m_tokens');
    if (input === null && output !== null) {
      return output / 1000;
    }
    const textTokPer1k = 1000 / 4;
    if (model.provider_id === 'openai' && input !== null && output !== null) {
      return textTokPer1k * (input / 1_000_000 + 6 * (output / 1_000_000));
    }
    if (input !== null && output !== null) {
      const audioTokPer1kChars = (1000 / 14) * 25;
      return textTokPer1k * (input / 1_000_000) + audioTokPer1kChars * (output / 1_000_000);
    }
    return null;
  }

  function initializeFiltersFromUrl() {
    modelFilters = {
      provider_id: page.url.searchParams.get('provider_id') ?? '',
      model_class: page.url.searchParams.get('model_class') ?? ''
    };
    const rawHost = page.url.searchParams.get('hosting') ?? '';
    const hostSelected = new Set(
      rawHost
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean)
    );
    hostingToggles = {
      cloud: hostSelected.has('cloud'),
      local: hostSelected.has('local')
    };
    const rawKinds = page.url.searchParams.get('model_kind') ?? '';
    const selected = new Set(
      rawKinds
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean)
    );
    modelKindToggles = {
      chat: selected.has('chat'),
      tts: selected.has('tts'),
      stt: selected.has('stt'),
      embedding: selected.has('embedding'),
      image_gen: selected.has('image_gen')
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
      const fetchFilters = catalogFetchFilters();
      const kinds = MODEL_KIND_FILTER_IDS.filter((k) => modelKindToggles[k]);
      const payload = await listCatalogModels(fetchFilters);
      catalogVersion = payload.data.catalog_version;
      let list = payload.data.models;
      // API accepts only one model_kind; with multiple toggles on, narrow results on the client.
      if (kinds.length > 1) {
        list = list.filter((m) => kinds.some((k) => k === m.model_kind));
      }
      models = list;
    } catch (err) {
      modelsError = err instanceof Error ? err.message : 'Failed to load catalog models.';
      models = [];
    } finally {
      modelsLoading = false;
    }
  }

  async function reloadBundledCatalog() {
    catalogReloadBusy = true;
    try {
      const payload = await reloadModelCatalog();
      notify(
        'success',
        `Catalog v${payload.data.catalog_version} reloaded (${payload.data.provider_count} providers, ${payload.data.model_count} models).`
      );
      await loadProviders();
      if (prefs.activeTab === 'models') {
        await loadModels();
      }
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Catalog reload failed.');
    } finally {
      catalogReloadBusy = false;
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
    await prefs.setActiveTab(tab, tab === 'models' ? modelsTabSearchParams() : {});
    if (tab === 'models' && models.length === 0 && !modelsLoading) {
      await loadModels();
    }
  }

  async function openModelsForProvider(providerId: string) {
    modelFilters = { ...modelFilters, provider_id: providerId };
    await prefs.setActiveTab('models', modelsTabSearchParams());
    await loadModels();
  }

  async function applyModelFilters() {
    await prefs.setActiveTab('models', modelsTabSearchParams());
    await loadModels();
  }

  async function clearModelFilters() {
    modelFilters = {
      provider_id: '',
      model_class: ''
    };
    modelKindToggles = emptyModelKindToggles();
    hostingToggles = emptyHostingToggles();
    await prefs.setActiveTab('models');
    await loadModels();
  }

  async function toggleModelKindFilter(kind: ModelKindFilterId) {
    modelKindToggles = { ...modelKindToggles, [kind]: !modelKindToggles[kind] };
    await applyModelFilters();
  }

  async function toggleHostingFilter(hosting: HostingFilterId) {
    hostingToggles = { ...hostingToggles, [hosting]: !hostingToggles[hosting] };
    await applyModelFilters();
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
    if (model.model_kind === 'image_gen') {
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
    if (model.model_kind === 'tts') {
      const est = ttsUsdPer1kCatalogEstimate(model, pricing as Record<string, unknown>);
      if (est !== null && Number.isFinite(est)) return formatTtsUsdPer1k(est);
      return '-';
    }
    if (model.model_kind === 'stt') {
      const perSecond = num('per_second');
      if (perSecond !== null) return `$${perSecond.toFixed(4)}/sec audio`;
    }
    return '-';
  }

  /** Build https URL from catalog `pricing.pricing_source` (often host/path; YAML may append notes in parentheses). */
  function pricingSourceHref(model: CatalogModelRow): string | null {
    const pricing = model.pricing;
    if (!pricing || typeof pricing !== 'object') return null;
    const raw = pricing['pricing_source'];
    if (typeof raw !== 'string') return null;
    let s = raw.trim();
    if (!s) return null;
    const paren = s.indexOf(' (');
    if (paren !== -1) s = s.slice(0, paren).trim();
    if (!s) return null;
    if (/^https?:\/\//i.test(s)) return s;
    if (s.startsWith('//')) return `https:${s}`;
    if (/^[a-z0-9][a-z0-9+.-]*\.[a-z]{2,}/i.test(s)) {
      return `https://${s.replace(/^\/+/, '')}`;
    }
    return null;
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
    <div class="flex flex-wrap items-center gap-2">
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
      <Button
        variant="outline"
        disabled={catalogReloadBusy}
        title="Reload bundled catalog.yaml on the server (clears in-memory cache)"
        onclick={reloadBundledCatalog}
      >
        <RefreshCw size={15} class={cn(catalogReloadBusy && 'animate-spin')} /> Reload catalog
      </Button>
    </div>
  </div>

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
        <div class="grid gap-1 font-sans text-xs font-semibold text-muted-foreground">
          <span id="catalog-kind-filters-label">Kind</span>
          <div
            class="flex h-9 items-center justify-center gap-0.5 rounded-md border bg-background px-1"
            role="group"
            aria-labelledby="catalog-kind-filters-label"
          >
            {#each MODEL_KIND_FILTER_IDS as kind (kind)}
              {@const { Icon, title } = MODEL_KIND_FILTER_UI[kind]}
              {@const on = modelKindToggles[kind]}
              <button
                type="button"
                class={cn(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-transparent transition-colors',
                  on
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-muted-foreground opacity-55 hover:opacity-100',
                  on && 'border-primary/20'
                )}
                title={title}
                aria-label={title}
                aria-pressed={on}
                onclick={() => toggleModelKindFilter(kind)}
              >
                <Icon size={16} strokeWidth={on ? 2.25 : 2} aria-hidden="true" />
              </button>
            {/each}
          </div>
        </div>
        <label class="grid gap-1 font-sans text-xs font-semibold text-muted-foreground">
          Class
          <select class="h-9 rounded-md border bg-background px-2 text-sm text-foreground" bind:value={modelFilters.model_class} onchange={applyModelFilters}>
            {#each modelClassOptions as option}
              <option value={option}>{option || 'All classes'}</option>
            {/each}
          </select>
        </label>
        <div class="grid gap-1 font-sans text-xs font-semibold text-muted-foreground">
          <span id="catalog-hosting-filters-label">Hosting</span>
          <div
            class="flex h-9 items-center justify-center gap-0.5 rounded-md border bg-background px-1"
            role="group"
            aria-labelledby="catalog-hosting-filters-label"
          >
            {#each HOSTING_FILTER_IDS as hosting (hosting)}
              {@const { Icon, title } = HOSTING_FILTER_UI[hosting]}
              {@const on = hostingToggles[hosting]}
              <button
                type="button"
                class={cn(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-transparent transition-colors',
                  on
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-muted-foreground opacity-55 hover:opacity-100',
                  on && 'border-primary/20'
                )}
                title={title}
                aria-label={title}
                aria-pressed={on}
                onclick={() => toggleHostingFilter(hosting)}
              >
                <Icon size={16} strokeWidth={on ? 2.25 : 2} aria-hidden="true" />
              </button>
            {/each}
          </div>
        </div>
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
              <span class="text-center">Context</span>
              <span>Pricing</span>
              <span>Features</span>
            </div>
            {#each models as model}
              {@const kindUi = modelKindUiForRow(model.model_kind)}
              {@const KindIcon = kindUi.Icon}
              {@const hostingUi = catalogHostingUiForRow(model.hosting)}
              {@const HostingIcon = hostingUi.Icon}
              {@const priceHref = pricingSourceHref(model)}
              <div class="grid min-h-16 grid-cols-[1fr_1.25fr_90px_110px_100px_100px_1fr_1.35fr] gap-3 border-t px-3 py-3">
                <span class="truncate text-sm">{providerLabels[model.provider_id] ?? model.provider_id}</span>
                <span class="min-w-0">
                  <strong class="flex min-w-0 items-baseline gap-1 font-sans text-sm">
                    {#if recommendedCatalogModelIds.has(model.id)}
                      <span
                        class="shrink-0 text-amber-500 dark:text-amber-400"
                        title="Recommended default in catalog for this provider and kind"
                        aria-hidden="true"
                      >★</span>
                      <span class="sr-only">Recommended. </span>
                    {/if}
                    <span class="min-w-0 truncate">{model.display_name}</span>
                  </strong>
                  <small class="block truncate text-xs text-muted-foreground">{model.id}</small>
                </span>
                <span class="flex justify-center">
                  <span class="inline-flex h-8 w-8 items-center justify-center rounded-md border bg-muted/40 text-foreground" title={kindUi.title}>
                    <KindIcon size={16} strokeWidth={2} aria-hidden="true" />
                    <span class="sr-only">{kindUi.title}</span>
                  </span>
                </span>
                <span class="truncate text-sm text-muted-foreground">{model.model_class ?? '-'}</span>
                <span class="flex justify-center">
                  <span class="inline-flex h-8 w-8 items-center justify-center rounded-md border bg-muted/40 text-foreground" title={hostingUi.title}>
                    <HostingIcon size={16} strokeWidth={2} aria-hidden="true" />
                    <span class="sr-only">{hostingUi.title}</span>
                  </span>
                </span>
                <span class="text-center font-sans text-xs text-muted-foreground">
                  {typeof model.context_window === 'number' ? model.context_window.toLocaleString() : '-'}
                </span>
                <span class="flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  <span class="min-w-0">{modelPricing(model)}</span>
                  {#if priceHref}
                    <a
                      href={priceHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      class="inline-flex shrink-0 text-primary hover:text-primary/90"
                      title="Open vendor pricing source"
                      aria-label="Open vendor pricing source in new tab"
                    >
                      <ArrowUpRight size={15} strokeWidth={2.25} aria-hidden="true" />
                    </a>
                  {/if}
                </span>
                <span class="min-w-0 text-sm leading-snug text-muted-foreground break-words" title={listText(model.features)}>{listText(model.features)}</span>
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

<ToastHost {toast} />

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
