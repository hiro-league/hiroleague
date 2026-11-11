<script lang="ts">
  /**
   * Catalog → Profiles → Uses, an extension's speaking (Phase 7b): the voice uses it declared (HomeHiro's
   * Speak) and the voice profile each speaks with (`voice.uses`). An alert or a Speak node can still pick
   * its own profile in the extension; this is the default.
   */
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import Notice from '$kit/ui/notice.svelte';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import type { VoiceController } from './voice-controller.svelte';

  let { voice, extension }: { voice: VoiceController; extension: string } = $props();

  const GRID = 'minmax(200px,1.1fr) minmax(170px,0.9fr) minmax(200px,1fr) minmax(240px,1.4fr)';
  const rows = $derived(voice.uses.extensions.find((e) => e.extension === extension)?.uses ?? []);
  let error = $state<string | null>(null);

  async function pick(key: string, profileId: string) {
    error = await voice.setUse(key, profileId || null);
  }
</script>

{#if rows.length}
  <div class="mt-3 grid gap-2">
    <div>
      <h4 class="font-sans text-base font-semibold text-primary">
        Speaking <span class="text-sm font-normal text-muted-foreground">· {rows.length} {rows.length === 1 ? 'use' : 'uses'}</span>
      </h4>
      <p class="text-xs text-muted-foreground">What it asks the core to say, and the voice profile it speaks with by default.</p>
    </div>
    {#if error}<Notice message={error} />{/if}
    <TableShell layout="grid" minWidth={900} gridColumns={GRID}>
      {#snippet headRow()}
        <span>Use</span>
        <span>Needs</span>
        <span>Voice</span>
        <span>Note</span>
      {/snippet}
      {#snippet body()}
        {#each rows as u (u.key)}
          {@const p = voice.profiles.find((x) => x.id === u.profile_id)}
          <div class={TABLE_GRID_ROW} style:grid-template-columns={GRID}>
            <span class="flex items-center gap-2 font-sans text-sm font-semibold">
              {u.name}
              {#if u.status === 'removed'}<Badge variant="outline">Removed</Badge>{/if}
            </span>
            <span><Badge variant="secondary">a voice clip</Badge></span>
            <span>
              <PickSelect
                class="h-8 w-full text-sm"
                label="Voice for {u.name}"
                value={u.profile_id ?? ''}
                options={[{ value: '', label: 'No voice picked' }, ...voice.profiles.map((vp) => ({ value: vp.id, label: vp.label }))]}
                onchange={(v) => pick(u.key, v)}
              />
            </span>
            <span class="text-sm text-muted-foreground">
              {#if p}{p.line}{:else if u.status === 'removed'}No longer declared.{:else}Nothing is said until a voice is picked.{/if}
            </span>
          </div>
        {/each}
      {/snippet}
    </TableShell>
  </div>
{/if}
