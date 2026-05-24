<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import DashboardPanel from '$lib/features/dashboard/DashboardPanel.svelte';
  import { createDashboardController } from '$lib/features/dashboard/state/dashboard-controller.svelte';

  const ctrl = createDashboardController();

  onMount(() => {
    void ctrl.load();
  });
</script>

<svelte:head>
  <title>Dashboard - Hiro Admin</title>
</svelte:head>

<AdminPageHeader
  kicker="Control Room"
  title="Hiro workspace status and operations."
  subtitle="Monitor configured providers, running workspaces, and gateway connectivity from the local admin server."
>
  {#snippet actions()}
    <div class="rounded-lg border border-primary/30 bg-primary/10 p-4 md:max-w-sm">
      <span class="font-sans text-sm text-muted-foreground">Admin package</span>
      <strong class="mt-1 block [overflow-wrap:anywhere] font-sans font-semibold">
        hirocli.admin_svelte.static
      </strong>
    </div>
  {/snippet}

  <DashboardPanel {ctrl} />
</AdminPageHeader>
