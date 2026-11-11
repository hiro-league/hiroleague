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
import { createResource } from '$lib/state/create-resource.svelte';
import { Action } from '$kit/state/action.svelte';
import type { ToastKind } from '$kit/ui/toast.svelte';

type Notify = (kind: ToastKind, message: string) => void;

export type ActiveProviderDialog = 'add' | 'remove' | null;

export function createActiveProvidersStore(notify: Notify = () => {}) {
  const listResource = createResource(
    async () => (await listActiveProviders()) ?? [],
    { initial: [] as ActiveProviderRow[], errorPrefix: 'Failed to load active providers.' }
  );

  // The "list addable providers" fetch (opening the add dialog) and the credential mutations below
  // each own their `busy`; the exposed `busy` getter is the union of both.
  const opening = new Action();
  const work = new Action();
  const test = new Action();
  let resolved = $state(false);
  let addableProviders = $state<AddableProviderRow[]>([]);
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

  const busy = $derived(opening.busy || work.busy);

  function closeDialog() {
    if (busy) return;
    dialog = null;
    selectedProvider = null;
  }

  async function openAddDialog(preferredProviderId?: string) {
    await opening.run(async () => {
      const payload = await listAddableProviders();
      addableProviders = payload;
      checkResult = null;
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
    });
    if (opening.error) notify('error', opening.error);
  }

  async function submitAddProvider() {
    const selected = addableProviderById(addForm.provider_id);
    const providerId = addForm.provider_id;
    const isLocal = selected?.auth_method === 'local_endpoint';
    await work.run(async () => {
      if (isLocal) await setLocalEndpoint(providerId, addForm.base_url);
      else await addProviderApiKey(providerId, addForm.api_key, addForm.account_id);
      dialog = null;
      await load({ silent: true });
    });
    if (work.error) notify('error', work.error);
    else notify('success', isLocal ? `Set endpoint for ${providerId}.` : `Stored API key for ${providerId}.`);
  }

  // Discard a stale dialog test result when the provider or endpoint changes.
  function clearCheckResult() {
    checkResult = null;
  }

  async function testConnection() {
    const providerId = addForm.provider_id;
    if (!providerId) return;
    checkResult = null;
    await test.run(async () => {
      checkResult = await checkProviderEndpoint(providerId, addForm.base_url);
    });
    if (test.error) notify('error', test.error);
  }

  async function probeProvider(providerId: string) {
    localStatus = {
      ...localStatus,
      [providerId]: { checking: true, result: localStatus[providerId]?.result ?? null }
    };
    try {
      const payload = await checkProviderEndpoint(providerId);
      localStatus = { ...localStatus, [providerId]: { checking: false, result: payload } };
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
    const count = await work.run(async () => {
      const imported = await scanProviderEnvironment();
      await load({ silent: true });
      return imported;
    });
    if (work.error) notify('error', work.error);
    else if (count === 0) notify('info', 'No new keys imported.');
    else if (count) notify('success', `Imported ${count} provider key${count === 1 ? '' : 's'} from the environment.`);
  }

  function openRemoveDialog(provider: ActiveProviderRow) {
    selectedProvider = provider;
    dialog = 'remove';
  }

  async function submitRemoveProvider() {
    if (!selectedProvider) return;
    const { provider_id } = selectedProvider;
    const removed = await work.run(async () => {
      const done = await removeProvider(provider_id);
      dialog = null;
      selectedProvider = null;
      await load({ silent: true });
      return done;
    });
    if (work.error) notify('error', work.error);
    else if (removed) notify('success', `Removed credentials for ${provider_id}.`);
    else notify('warning', 'Provider was not configured.');
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
      return opening.busy;
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
      return test.busy;
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
