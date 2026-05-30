<script lang="ts">
  import { RefreshCw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    catalogReloadBusy?: boolean;
    refreshBusy?: boolean;
    onRefresh: () => void;
  };

  let { catalogReloadBusy = false, refreshBusy = false, onRefresh }: Props = $props();
</script>

<Button
  variant="outline"
  disabled={refreshBusy || catalogReloadBusy}
  title="Re-fetch this list from the server using the catalog already loaded in memory"
  onclick={() => void onRefresh()}
>
  <RefreshCw size={15} class={cn(refreshBusy && 'animate-spin')} />
  Refresh
</Button>
