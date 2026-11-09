<script lang="ts">
  /**
   * Catalog → AI profiles, the default profiles of Hiro's jobs (Phase 7b MOCKUP), drawn as rows of
   * the same table as your own profiles. Today's 8 locked tuning presets become these, each with the
   * model its job uses today; they can be edited but not deleted, and Restore default brings one back.
   */
  import { Pencil, RotateCcw, Copy, Trash2 } from '@lucide/svelte';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { AiProfile } from '$lib/features/catalog/ai/ai-types';
  import { jobsUsing, MOCK_DEFAULT_PROFILES, toAiProfile } from './phase7b';

  let { grid, onedit }: { grid: string; onedit: (p: AiProfile) => void } = $props();
</script>

{#each MOCK_DEFAULT_PROFILES as p (p.id)}
  {@const jobs = jobsUsing(p.id)}
  <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={grid}>
    <span class="grid content-start gap-1">
      <span class="flex flex-wrap items-center gap-1.5">
        <span class="font-sans text-sm font-semibold">{p.name}</span>
        {#if p.fromPreset}
          <Badge variant="outline">Default</Badge>
          <FieldHelp text={`Hiro's default for this job (it was the "${p.fromPreset}" preset). Edit it freely; Restore default brings back its first settings.`} />
        {/if}
      </span>
      {#if jobs.length}
        <span class="text-xs text-muted-foreground">Used by Hiro: {jobs.join(', ')}</span>
      {/if}
    </span>
    <span class="grid content-start gap-1">
      <span class="flex items-center gap-2">
        <span class="truncate font-sans text-sm">{p.model}</span>
        <Badge variant="outline">API</Badge>
      </span>
      <span class="truncate text-xs text-muted-foreground">{p.provider}</span>
    </span>
    <span class="text-sm">{p.thinking}</span>
    <span class="grid content-start gap-1">
      <span class="text-sm">{p.budget}</span>
      <span class="text-xs text-muted-foreground">{p.today}</span>
    </span>
    <span class="text-sm text-muted-foreground">{p.fallback ? `→ ${p.fallback}` : 'None'}</span>
    <span class="flex flex-wrap justify-end gap-2">
      <Button size="sm" variant="outline" onclick={() => onedit(toAiProfile(p))}><Pencil size={13} /> Edit</Button>
      <Button size="sm" variant="outline"><Copy size={13} /> Duplicate</Button>
      {#if p.fromPreset}
        <Button size="sm" variant="outline" title="Back to the settings it started with"><RotateCcw size={13} /> Restore default</Button>
      {:else}
        <Button size="sm" variant="destructive-outline"><Trash2 size={13} /> Delete</Button>
      {/if}
    </span>
  </div>
{/each}
