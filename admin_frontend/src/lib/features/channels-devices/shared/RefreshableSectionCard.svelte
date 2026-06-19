<script lang="ts">
  import type { Snippet } from 'svelte';
  import { RefreshCw } from '@lucide/svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';

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

<SectionCard class="grid gap-4">
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
    <InlineLoading label={loadingLabel} />
  {:else if error}
    <InlineDestructiveAlert title={errorTitle} message={error} />
  {:else if empty}
    <InlineEmptyState message={emptyMessage} />
  {:else}
    {@render children?.()}
  {/if}
</SectionCard>
