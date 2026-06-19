<script lang="ts">
  /** Generic avatar + name table cell, shared by admin ledger/list tables (graph runs, memories). */
  let { photo, name }: { photo: string | null; name: string } = $props();
</script>

<td class="avatar-name-cell">
  <div class="avatar-name-inner">
    {#if photo}
      <img class="avatar-name-img" src={photo} alt="" width="32" height="32" />
    {:else}
      <div class="avatar-name-img avatar-name-img--placeholder" aria-hidden="true"></div>
    {/if}
    <span class="avatar-name-label">{name}</span>
  </div>
</td>

<style>
  .avatar-name-cell {
    max-width: 220px;
    vertical-align: middle;
  }

  .avatar-name-inner {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .avatar-name-img {
    width: 32px;
    height: 32px;
    border-radius: 999px;
    object-fit: cover;
    flex-shrink: 0;
    display: block;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, #000 10%, transparent);
  }

  .avatar-name-img--placeholder {
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 18%, transparent);
  }

  .avatar-name-label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
