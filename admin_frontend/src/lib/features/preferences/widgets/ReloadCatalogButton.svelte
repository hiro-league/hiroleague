<script lang="ts">
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import { BookOpen, RefreshCw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    busy: boolean;
    catalogReloadBusy: boolean;
    onReload: () => void;
  };

  let { busy, catalogReloadBusy, onReload }: Props = $props();
</script>

<Button
  variant="outline"
  size="sm"
  class="shrink-0"
  disabled={busy}
  title="Open Model Catalog (bundled providers and models)"
  onclick={() => void goto(`${base}/catalog/`)}
>
  <BookOpen size={14} /> Model catalog
</Button>
<Button
  variant="outline"
  size="sm"
  class="shrink-0"
  disabled={busy || catalogReloadBusy}
  title="Reload bundled catalog.yaml on the server (clears in-memory cache)"
  onclick={onReload}
>
  <RefreshCw size={14} class={cn(catalogReloadBusy && 'animate-spin')} /> Reload catalog
</Button>
