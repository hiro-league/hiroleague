<script lang="ts">
  import { onMount } from 'svelte';
  import { KeyRound, RefreshCw, Search, Trash2 } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Modal from '$lib/ui/Modal.svelte';
  import {
    addProviderApiKey,
    listActiveProviders,
    listAddableProviders,
    removeProvider,
    scanProviderEnvironment,
    type ActiveProviderRow,
    type AddableProviderRow
  } from '$lib/api/catalog';
  import { cn } from '$lib/utils';

  let activeProviders = $state<ActiveProviderRow[]>([]);
  let addableProviders = $state<AddableProviderRow[]>([]);
  let activeProvidersLoading = $state(true);
  let addableProvidersLoading = $state(false);
  let activeProvidersBusy = $state(false);
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

  onMount(loadActiveProviders);
</script>

<section class="grid max-w-[1420px] gap-5">
  <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">AI Models</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Active Providers</h2>
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

  <section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
    <div>
      <h3 class="text-lg font-semibold">Configured providers</h3>
      <span class="font-sans text-sm text-muted-foreground">
        {activeProviderCounts.total} configured / {activeProviderCounts.cloud} cloud / {activeProviderCounts.local} local
      </span>
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
