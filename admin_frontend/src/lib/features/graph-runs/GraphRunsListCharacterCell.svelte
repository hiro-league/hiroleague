<script lang="ts">
  /** Shared avatar + name column for ledger and Mem0 tables (GraphRuns step #2 extraction). */
  let { photo, name }: { photo: string | null; name: string } = $props();
</script>

<td class="runs-list-character-cell">
  <div class="runs-list-character-inner">
    {#if photo}
      <img class="runs-list-avatar" src={photo} alt="" width="32" height="32" />
    {:else}
      <div class="runs-list-avatar runs-list-avatar--placeholder" aria-hidden="true"></div>
    {/if}
    <span class="runs-list-character-name">{name}</span>
  </div>
</td>

<style>
  .runs-list-character-cell {
    max-width: 220px;
    vertical-align: middle;
  }

  .runs-list-character-inner {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .runs-list-avatar {
    width: 32px;
    height: 32px;
    border-radius: 999px;
    object-fit: cover;
    flex-shrink: 0;
    display: block;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, #000 10%, transparent);
  }

  .runs-list-avatar--placeholder {
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 18%, transparent);
  }

  .runs-list-character-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
