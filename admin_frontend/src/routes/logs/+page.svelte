<script lang="ts">
  import AdminShell from '$lib/shell/AdminShell.svelte';
  import LogsPage from '$lib/features/logs/LogsPage.svelte';
</script>

<AdminShell activePath="logs">
  <LogsPage />
</AdminShell>
