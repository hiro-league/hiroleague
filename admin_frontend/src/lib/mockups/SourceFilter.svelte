<script lang="ts" module>
  export type SourceOption = { id: string; label: string; count: number };
</script>

<script lang="ts">
  /**
   * Phase 7b MOCKUP: who a profile serves — All, Hiro (the core's own jobs and characters), each
   * extension, and Unused (for cleanup). A profile used by both Hiro and Home shows under both.
   * Used on AI profiles and voice profiles, so the core's and the extensions' profiles don't mix.
   */
  import { cn } from '$lib/utils';

  let { options, value, onchange }: { options: SourceOption[]; value: string; onchange: (id: string) => void } = $props();

  const pill = (on: boolean) =>
    cn(
      'rounded-md px-2.5 py-1 font-sans text-xs font-medium transition-colors',
      on ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:bg-accent hover:text-foreground'
    );
</script>

<span class="inline-flex flex-wrap gap-1 rounded-lg border bg-card p-1" role="group" aria-label="Show profiles for">
  {#each options as o (o.id)}
    <button type="button" class={pill(value === o.id)} aria-pressed={value === o.id} onclick={() => onchange(o.id)}>
      {o.label} <span class="opacity-70">({o.count})</span>
    </button>
  {/each}
</span>
