<script lang="ts">
  /**
   * The local servers (LM Studio, Ollama) as their providers' rows in the Providers list: the page
   * asks `ProvidersTab` to skip the catalog's own rows for them and draws these instead, with the
   * live status (`GET /api/ai/local-servers`). The action opens the server dialog.
   */
  import type { CatalogProviderRow } from '$lib/api/catalog';
  import { dateTime } from '$lib/format/time';
  import AiProviderRow from './AiProviderRow.svelte';
  import type { AiController } from './ai-controller.svelte';
  import { LOCAL_SERVER_IDS, LOCAL_SERVER_KIND_LABELS, serverInfo, serverStatus } from './ai-profile-rules';
  import type { ProviderRowStatus } from './ai-types';

  let {
    ai,
    catalogProviders,
    activeOnly
  }: { ai: AiController; catalogProviders: CatalogProviderRow[]; activeOnly: boolean } = $props();

  const CHECKING: ProviderRowStatus = { tone: 'off', word: 'checking', title: 'Checking the server…' };
  // The servers couldn't be read at all (the row stays, with why in its tooltip).
  const UNKNOWN: ProviderRowStatus = { tone: 'off', word: 'unknown', title: 'Could not check the server' };

  const rows = $derived(
    LOCAL_SERVER_IDS.map((id) => ({
      id,
      name: catalogProviders.find((p) => p.id === id)?.display_name ?? `${LOCAL_SERVER_KIND_LABELS[id]} (local)`,
      server: ai.serverFor(id)
    })).filter((r) => !activeOnly || r.server?.configured || r.server?.state === 'up')
  );
</script>

{#each rows as row (row.id)}
  {@const server = row.server}
  {@const loaded = server?.models.find((m) => m.loaded || m.loaded_by_core)}
  <AiProviderRow
    name={row.name}
    id={row.id}
    status={server ? serverStatus(server) : ai.serversLoading ? CHECKING : UNKNOWN}
    hosting="local"
    auth="local_endpoint"
    models={server?.models.length ?? 0}
    kinds="chat"
    recommended={loaded ? { kind: 'loaded', name: loaded.display_name || loaded.name, id: loaded.id } : null}
    updated={server ? (server.checked_at ? dateTime(server.checked_at) : '—') : '-'}
    info={server ? serverInfo(server, ai.profilesOnProvider(row.id)) : (ai.serversError ?? 'Checking the server…')}
    actionLabel="Server"
    onAction={() => ai.openProviderDialog(row.id)}
  />
{/each}
