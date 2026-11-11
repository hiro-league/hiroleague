<script lang="ts">
  import { onMount } from 'svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import DashboardPanel from '$lib/features/dashboard/DashboardPanel.svelte';
  import { createDashboardController } from '$lib/features/dashboard/state/dashboard-controller.svelte';
  import AppsCard from '$lib/features/apps/AppsCard.svelte';

  const ctrl = createDashboardController();

  onMount(() => {
    void ctrl.load();
  });
</script>

<svelte:head>
  <title>Dashboard - Hiro Admin</title>
</svelte:head>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Dashboard" description="Hiro workspace status and operations: configured providers, running workspaces and gateway connectivity.">
    {#snippet actions()}
    <!-- UI kit step 3: a quiet line in the compact header (it was a tinted box in the tall one). -->
    <span class="text-xs text-muted-foreground">Admin package <code>hirocli.admin_svelte.static</code></span>
    {/snippet}
  </PageHeader>
  

  <!-- Phase 8: the Apps card opens each extension's own site in a new tab. -->
  <div class="mb-5 empty:hidden"><AppsCard /></div>
  <DashboardPanel {ctrl} />
</section>
