<script lang="ts">
  import AdminShell from '$lib/shell/AdminShell.svelte';
  import ActiveProvidersPage from '$lib/features/catalog/ActiveProvidersPage.svelte';
</script>

<AdminShell activePath="active-providers">
  <ActiveProvidersPage />
</AdminShell>
