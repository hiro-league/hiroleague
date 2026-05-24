<script lang="ts">
  import { RefreshCw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    catalogReloadBusy?: boolean;
    refreshBusy?: boolean;
    onReload: () => void;
    onRefresh: () => void;
  };

  let { catalogReloadBusy = false, refreshBusy = false, onReload, onRefresh }: Props = $props();
</script>

<div class="flex flex-wrap items-center gap-2">
  <Button
    variant="outline"
    disabled={catalogReloadBusy || refreshBusy}
    title="Re-read bundled catalog.yaml from disk on the server, clear the in-memory cache, then update this tab"
    onclick={() => void onReload()}
  >
    <RefreshCw size={15} class={cn(catalogReloadBusy && 'animate-spin')} />
    Reload catalog
  </Button>
  <Button
    variant="outline"
    disabled={refreshBusy || catalogReloadBusy}
    title="Re-fetch this list from the server using the catalog already loaded in memory"
    onclick={() => void onRefresh()}
  >
    <RefreshCw size={15} class={cn(refreshBusy && 'animate-spin')} />
    Refresh
  </Button>
</div>
