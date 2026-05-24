<script lang="ts">
  import { onMount } from 'svelte';
  import { KeyRound, RefreshCw, Search } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import ActiveProvidersPanel from '$lib/catalog/active-providers/ActiveProvidersPanel.svelte';
  import { createActiveProvidersStore } from '$lib/catalog/active-providers/active-providers-store.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';

  const toasts = createToastNotifier();
  const store = createActiveProvidersStore();

  onMount(() => {
    void store.load();
  });
</script>

<AdminPageHeader kicker="AI Models" title="Active Providers" sticky>
  {#snippet actions()}
    <Button variant="outline" disabled={store.busy} onclick={() => void store.load()}>
      <RefreshCw size={15} /> Refresh
    </Button>
    <Button variant="outline" disabled={store.busy} onclick={() => void store.scanEnvironment(toasts.notify)}>
      <Search size={15} /> Scan environment
    </Button>
    <Button disabled={store.busy} onclick={() => void store.openAddDialog(toasts.notify)}>
      <KeyRound size={15} /> Add API key
    </Button>
  {/snippet}

  <ActiveProvidersPanel {store} notify={toasts.notify} />
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
