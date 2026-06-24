<script lang="ts">
  import { base } from '$app/paths';
  import { goto, invalidateAll } from '$app/navigation';
  import { page } from '$app/state';
  import Button from '$lib/components/ui/button.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import { RefreshCw } from '@lucide/svelte';

  const message = $derived(page.error?.message ?? 'Something went wrong. Please try again.');
  const status = $derived(page.status ?? 500);

  async function retry() {
    await invalidateAll();
    if (page.error) {
      location.reload();
    }
  }
</script>

<div class="mx-auto flex max-w-lg flex-col gap-4 py-8">
  <div class="space-y-1">
    <h1 class="font-sans text-2xl font-semibold tracking-tight">Something went wrong</h1>
    {#if status !== 500}
      <p class="font-sans text-sm text-muted-foreground">Error {status}</p>
    {/if}
  </div>

  <InlineDestructiveAlert title="Error" {message} />

  <div class="flex flex-wrap gap-2">
    <Button onclick={() => void retry()}>
      <RefreshCw size={14} />
      Retry
    </Button>
    <Button variant="outline" onclick={() => goto(`${base}/`)}>Back to dashboard</Button>
  </div>
</div>
