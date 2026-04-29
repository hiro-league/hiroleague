<script lang="ts">
  import AdminShell from '$lib/shell/AdminShell.svelte';
  import CharactersPage from '$lib/features/characters/CharactersPage.svelte';
</script>

<AdminShell activePath="characters">
  <CharactersPage />
</AdminShell>
