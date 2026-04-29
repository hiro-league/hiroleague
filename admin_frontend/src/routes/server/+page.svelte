<script lang="ts">
  import AdminShell from '$lib/shell/AdminShell.svelte';
  import ServerPage from '$lib/features/server/ServerPage.svelte';
</script>

<AdminShell activePath="server">
  <ServerPage />
</AdminShell>
