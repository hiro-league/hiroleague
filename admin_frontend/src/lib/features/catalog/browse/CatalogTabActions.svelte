<script lang="ts">
  import { RefreshCw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    catalogReloadBusy?: boolean;
    refreshBusy?: boolean;
    onRefresh: () => void;
    /** When provided, render a "Reload catalog" button next to Refresh (Providers tab). */
    onReloadCatalog?: () => void;
  };

  let { catalogReloadBusy = false, refreshBusy = false, onRefresh, onReloadCatalog }: Props = $props();
</script>

{#if onReloadCatalog}
  <Button
    variant="outline"
    disabled={refreshBusy || catalogReloadBusy}
    title="Re-read bundled catalog.yaml from disk on the server, clear the in-memory cache, then refresh lists"
    onclick={() => void onReloadCatalog()}
  >
    <RefreshCw size={15} class={cn(catalogReloadBusy && 'animate-spin')} />
    Reload catalog
  </Button>
{/if}
<Button
  variant="outline"
  disabled={refreshBusy || catalogReloadBusy}
  title="Re-fetch this list from the server using the catalog already loaded in memory"
  onclick={() => void onRefresh()}
>
  <RefreshCw size={15} class={cn(refreshBusy && 'animate-spin')} />
  Refresh
</Button>
