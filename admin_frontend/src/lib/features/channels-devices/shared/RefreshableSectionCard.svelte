<script lang="ts">
  import type { Snippet } from 'svelte';
  import { RefreshCw } from '@lucide/svelte';
  import Panel from '$kit/ui/panel.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import Notice from '$kit/ui/notice.svelte';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import Loading from '$kit/ui/loading.svelte';

  type Props = {
    title: string;
    countText: string;
    loading: boolean;
    error: string | null;
    empty: boolean;
    loadingLabel: string;
    errorTitle: string;
    emptyMessage: string;
    onRefresh: () => void;
    children?: Snippet;
  };

  let {
    title,
    countText,
    loading,
    error,
    empty,
    loadingLabel,
    errorTitle,
    emptyMessage,
    onRefresh,
    children
  }: Props = $props();
</script>

<Panel class="grid gap-4">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class="text-lg font-semibold">{title}</h3>
      <span class="font-sans text-sm text-muted-foreground">{countText}</span>
    </div>
    <Button variant="outline" disabled={loading} onclick={onRefresh}>
      <RefreshCw size={15} /> Refresh
    </Button>
  </div>

  {#if loading}
    <Loading label={loadingLabel} />
  {:else if error}
    <Notice title={errorTitle} message={error} />
  {:else if empty}
    <EmptyState message={emptyMessage} />
  {:else}
    {@render children?.()}
  {/if}
</Panel>
