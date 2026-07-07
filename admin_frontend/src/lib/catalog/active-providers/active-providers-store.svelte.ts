import {
  addProviderApiKey,
  checkProviderEndpoint,
  listActiveProviders,
  listAddableProviders,
  removeProvider,
  scanProviderEnvironment,
  setLocalEndpoint,
  type ActiveProviderRow,
  type AddableProviderRow,
  type ProviderCheckResult
} from '$lib/api/catalog';
import { createMutation, createResource } from '$lib/state/create-resource.svelte';
import type { ToastKind } from '$lib/ui/toast-types';

type Notify = (kind: ToastKind, message: string) => void;

export type ActiveProviderDialog = 'add' | 'remove' | null;

export function createActiveProvidersStore(notify: Notify = () => {}) {
  const listResource = createResource(
    async () => (await listActiveProviders()).data ?? [],
    { initial: [] as ActiveProviderRow[], errorPrefix: 'Failed to load active providers.' }
  );

  // True only while the (non-mutation) "list addable providers" fetch runs; the credential
  // mutations below each own their `.busy`. The exposed `busy` getter is the union of both.
  let openingDialog = $state(false);
  let resolved = $state(false);
  let addableProviders = $state<AddableProviderRow[]>([]);
  let addableProvidersLoading = $state(false);
  let dialog = $state<ActiveProviderDialog>(null);
  let selectedProvider = $state<ActiveProviderRow | null>(null);
  let addForm = $state({
    provider_id: '',
    api_key: '',
    // Cloudflare-style vendors need a non-secret account id alongside the API key.
    account_id: '',
    // Local providers (Ollama, LM Studio): HTTP endpoint instead of an API key.
    base_url: ''
  });

  function addableProviderById(providerId: string): AddableProviderRow | undefined {
    return addableProviders.find((provider) => provider.id === providerId);
  }

  // Dialog "Test connection" state (probe of the candidate endpoint before saving).
  let checking = $state(false);
  let checkResult = $state<ProviderCheckResult | null>(null);
  // Live reachability per configured local provider, keyed by provider_id (probed on load).
  type ProviderStatus = { checking: boolean; result: ProviderCheckResult | null };
  let localStatus = $state<Record<string, ProviderStatus>>({});

  const counts = $derived(
    listResource.data.reduce(
      (acc, provider) => {
        acc.total += 1;
        if (provider.hosting === 'cloud') acc.cloud += 1;
        if (provider.hosting === 'local') acc.local += 1;
        return acc;
      },
      { total: 0, cloud: 0, local: 0 }
    )
  );

  const configuredProviderIds = $derived(new Set(listResource.data.map((row) => row.provider_id)));

  // Per-id lookup so the merged providers table can join catalog rows to their configured state.
  const rowsByProviderId = $derived(
    new Map(listResource.data.map((row) => [row.provider_id, row]))
  );

  function providerKindLabel(provider: ActiveProviderRow): string {
    const kinds = [];
    if (provider.has_chat) kinds.push('chat');
    if (provider.has_tts) kinds.push('tts');
    if (provider.has_stt) kinds.push('stt');
    if (provider.has_embedding) kinds.push('embedding');
    if (provider.has_rerank) kinds.push('rerank');
    if (provider.has_image_gen) kinds.push('image');
    return kinds.length ? kinds.join(', ') : '-';
  }

  function activeProviderIdsFor(
    predicate: (row: ActiveProviderRow) => boolean
  ): Set<string> {
    return new Set(listResource.data.filter(predicate).map((row) => row.provider_id));
  }

  async function load(options: { silent?: boolean } = {}) {
    await listResource.load({ silent: options.silent });
    if (listResource.error) {
      resolved = false;
      return;
    }
    resolved = true;
    probeConfiguredLocal();
  }

  // ── Credential mutations ────────────────────────────────────────────────────
  // Hoisted so each owns its busy/try-catch/notify envelope, instead of allocating a throwaway
  // mutation per click. successMsg is a thunk because it reads the current form/selection at run
  // time; the add path splits by auth_method so each branch keeps a correct static errorPrefix.
  async function afterAddMutate() {
    dialog = null;
    await load({ silent: true });
  }

  const setEndpointMutation = createMutation(
    () => setLocalEndpoint(addForm.provider_id, addForm.base_url),
    {
      notify,
      successMsg: () => `Set endpoint for ${addForm.provider_id}.`,
      errorPrefix: 'Failed to set endpoint.',
      onDone: afterAddMutate
    }
  );

  const addKeyMutation = createMutation(
    () => addProviderApiKey(addForm.provider_id, addForm.api_key, addForm.account_id),
    {
      notify,
      successMsg: () => `Stored API key for ${addForm.provider_id}.`,
      errorPrefix: 'Failed to store API key.',
      onDone: afterAddMutate
    }
  );

  const scanMutation = createMutation(async () => (await scanProviderEnvironment()).data, {
    notify,
    successMsg: (count) =>
      count > 0
        ? `Imported ${count} provider key${count === 1 ? '' : 's'} from the environment.`
        : undefined,
    errorPrefix: 'Environment scan failed.',
    onDone: async (count) => {
      if (count === 0) notify('info', 'No new keys imported.');
      await load({ silent: true });
    }
  });

  const removeMutation = createMutation(
    async () => (await removeProvider(selectedProvider!.provider_id)).data,
    {
      notify,
      successMsg: (removed) =>
        removed ? `Removed credentials for ${selectedProvider!.provider_id}.` : undefined,
      errorPrefix: 'Remove provider failed.',
      onDone: async (removed) => {
        if (!removed) notify('warning', 'Provider was not configured.');
        dialog = null;
        selectedProvider = null;
        await load({ silent: true });
      }
    }
  );

  const busy = $derived(
    openingDialog ||
      setEndpointMutation.busy ||
      addKeyMutation.busy ||
      scanMutation.busy ||
      removeMutation.busy
  );

  function closeDialog() {
    if (busy) return;
    dialog = null;
    selectedProvider = null;
  }

  async function openAddDialog(preferredProviderId?: string) {
    openingDialog = true;
    addableProvidersLoading = true;
    try {
      const payload = await listAddableProviders();
      addableProviders = payload.data;
      checkResult = null;
      checking = false;
      // Per-row "Add" passes the clicked provider so the dialog opens preselected to it;
      // the generic add button falls back to the first addable provider.
      const chosen =
        (preferredProviderId && addableProviderById(preferredProviderId)) || addableProviders[0];
      addForm = {
        provider_id: chosen?.id ?? '',
        api_key: '',
        account_id: '',
        // Prefill the suggested endpoint for local providers (blank for cloud).
        base_url: chosen?.default_base_url ?? ''
      };
      if (addableProviders.length === 0) {
        notify('info', 'All catalog providers are already configured.');
        return;
      }
      dialog = 'add';
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to list addable providers.');
    } finally {
      openingDialog = false;
      addableProvidersLoading = false;
    }
  }

  async function submitAddProvider() {
    const selected = addableProviderById(addForm.provider_id);
    const isLocal = selected?.auth_method === 'local_endpoint';
    await (isLocal ? setEndpointMutation : addKeyMutation).run();
  }

  // Discard a stale dialog test result when the provider or endpoint changes.
  function clearCheckResult() {
    checkResult = null;
  }

  async function testConnection() {
    const providerId = addForm.provider_id;
    if (!providerId) return;
    checking = true;
    checkResult = null;
    try {
      const payload = await checkProviderEndpoint(providerId, addForm.base_url);
      checkResult = payload.data;
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Connection test failed.');
    } finally {
      checking = false;
    }
  }

  async function probeProvider(providerId: string) {
    localStatus = {
      ...localStatus,
      [providerId]: { checking: true, result: localStatus[providerId]?.result ?? null }
    };
    try {
      const payload = await checkProviderEndpoint(providerId);
      localStatus = { ...localStatus, [providerId]: { checking: false, result: payload.data } };
    } catch {
      // Treat a failed probe request as "unknown" (no result) rather than surfacing a toast on load.
      localStatus = { ...localStatus, [providerId]: { checking: false, result: null } };
    }
  }

  function probeConfiguredLocal() {
    for (const row of listResource.data) {
      // Only providers configured by HTTP endpoint — skip cloud and the built-in in-process 'local'.
      if (row.auth_method === 'local_endpoint') void probeProvider(row.provider_id);
    }
  }

  async function scanEnvironment() {
    await scanMutation.run();
  }

  function openRemoveDialog(provider: ActiveProviderRow) {
    selectedProvider = provider;
    dialog = 'remove';
  }

  async function submitRemoveProvider() {
    if (!selectedProvider) return;
    await removeMutation.run();
  }

  return {
    get rows(): ActiveProviderRow[] {
      return listResource.data;
    },
    get loading(): boolean {
      return listResource.loading;
    },
    get error(): string | null {
      return listResource.error;
    },
    get busy(): boolean {
      return busy;
    },
    get resolved(): boolean {
      return resolved;
    },
    get counts() {
      return counts;
    },
    get configuredProviderIds(): Set<string> {
      return configuredProviderIds;
    },
    get rowsByProviderId(): Map<string, ActiveProviderRow> {
      return rowsByProviderId;
    },
    get chatActiveProviderIds(): Set<string> {
      return activeProviderIdsFor((row) => row.has_chat);
    },
    get sttActiveProviderIds(): Set<string> {
      return activeProviderIdsFor((row) => row.has_stt);
    },
    get ttsActiveProviderIds(): Set<string> {
      return activeProviderIdsFor((row) => row.has_tts);
    },
    get embeddingActiveProviderIds(): Set<string> {
      return activeProviderIdsFor((row) => row.has_embedding);
    },
    get rerankActiveProviderIds(): Set<string> {
      return activeProviderIdsFor((row) => row.has_rerank);
    },
    get addableProviders(): AddableProviderRow[] {
      return addableProviders;
    },
    get addableProvidersLoading(): boolean {
      return addableProvidersLoading;
    },
    get dialog(): ActiveProviderDialog {
      return dialog;
    },
    get selectedProvider(): ActiveProviderRow | null {
      return selectedProvider;
    },
    get addForm() {
      return addForm;
    },
    set addForm(value: {
      provider_id: string;
      api_key: string;
      account_id: string;
      base_url: string;
    }) {
      addForm = value;
    },
    get checking(): boolean {
      return checking;
    },
    get checkResult(): ProviderCheckResult | null {
      return checkResult;
    },
    get localStatus(): Record<string, ProviderStatus> {
      return localStatus;
    },
    providerKindLabel,
    load,
    closeDialog,
    openAddDialog,
    submitAddProvider,
    testConnection,
    clearCheckResult,
    probeProvider,
    scanEnvironment,
    openRemoveDialog,
    submitRemoveProvider
  };
}

export type ActiveProvidersStore = ReturnType<typeof createActiveProvidersStore>;
