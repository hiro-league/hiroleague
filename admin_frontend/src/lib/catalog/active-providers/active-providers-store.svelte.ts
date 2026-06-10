import {
  addProviderApiKey,
  listActiveProviders,
  listAddableProviders,
  removeProvider,
  scanProviderEnvironment,
  type ActiveProviderRow,
  type AddableProviderRow
} from '$lib/api/catalog';
import type { ToastKind } from '$lib/ui/toast-types';

type Notify = (kind: ToastKind, message: string) => void;

export type ActiveProviderDialog = 'add' | 'remove' | null;

export function createActiveProvidersStore() {
  let rows = $state<ActiveProviderRow[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let resolved = $state(false);
  let addableProviders = $state<AddableProviderRow[]>([]);
  let addableProvidersLoading = $state(false);
  let dialog = $state<ActiveProviderDialog>(null);
  let selectedProvider = $state<ActiveProviderRow | null>(null);
  let addForm = $state({
    provider_id: '',
    api_key: '',
    // Cloudflare-style vendors need a non-secret account id alongside the API key.
    account_id: ''
  });

  const counts = $derived(
    rows.reduce(
      (acc, provider) => {
        acc.total += 1;
        if (provider.hosting === 'cloud') acc.cloud += 1;
        if (provider.hosting === 'local') acc.local += 1;
        return acc;
      },
      { total: 0, cloud: 0, local: 0 }
    )
  );

  const configuredProviderIds = $derived(new Set(rows.map((row) => row.provider_id)));

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
    return new Set(rows.filter(predicate).map((row) => row.provider_id));
  }

  async function load(options: { silent?: boolean } = {}) {
    if (!options.silent) {
      loading = true;
    }
    error = null;
    resolved = false;
    try {
      const payload = await listActiveProviders();
      rows = payload.data ?? [];
      resolved = true;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load active providers.';
      rows = [];
      resolved = false;
    } finally {
      if (!options.silent) {
        loading = false;
      }
    }
  }

  function closeDialog() {
    if (busy) return;
    dialog = null;
    selectedProvider = null;
  }

  async function openAddDialog(notify: Notify) {
    busy = true;
    addableProvidersLoading = true;
    try {
      const payload = await listAddableProviders();
      addableProviders = payload.data;
      addForm = {
        provider_id: addableProviders[0]?.id ?? '',
        api_key: '',
        account_id: ''
      };
      if (addableProviders.length === 0) {
        notify('info', 'All cloud catalog providers are already configured.');
        return;
      }
      dialog = 'add';
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to list addable providers.');
    } finally {
      busy = false;
      addableProvidersLoading = false;
    }
  }

  async function submitAddProvider(notify: Notify) {
    busy = true;
    try {
      await addProviderApiKey(addForm.provider_id, addForm.api_key, addForm.account_id);
      notify('success', `Stored API key for ${addForm.provider_id}.`);
      dialog = null;
      await load({ silent: true });
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to store API key.');
    } finally {
      busy = false;
    }
  }

  async function scanEnvironment(notify: Notify) {
    busy = true;
    try {
      const payload = await scanProviderEnvironment();
      const count = payload.data;
      notify(
        count > 0 ? 'success' : 'info',
        count > 0
          ? `Imported ${count} provider key${count === 1 ? '' : 's'} from the environment.`
          : 'No new keys imported.'
      );
      await load({ silent: true });
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Environment scan failed.');
    } finally {
      busy = false;
    }
  }

  function openRemoveDialog(provider: ActiveProviderRow) {
    selectedProvider = provider;
    dialog = 'remove';
  }

  async function submitRemoveProvider(notify: Notify) {
    if (!selectedProvider) return;
    busy = true;
    try {
      const payload = await removeProvider(selectedProvider.provider_id);
      notify(
        payload.data ? 'success' : 'warning',
        payload.data
          ? `Removed credentials for ${selectedProvider.provider_id}.`
          : 'Provider was not configured.'
      );
      dialog = null;
      selectedProvider = null;
      await load({ silent: true });
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Remove provider failed.');
    } finally {
      busy = false;
    }
  }

  return {
    get rows(): ActiveProviderRow[] {
      return rows;
    },
    get loading(): boolean {
      return loading;
    },
    get error(): string | null {
      return error;
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
    set addForm(value: { provider_id: string; api_key: string; account_id: string }) {
      addForm = value;
    },
    providerKindLabel,
    load,
    closeDialog,
    openAddDialog,
    submitAddProvider,
    scanEnvironment,
    openRemoveDialog,
    submitRemoveProvider
  };
}

export type ActiveProvidersStore = ReturnType<typeof createActiveProvidersStore>;
