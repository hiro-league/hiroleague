<script lang="ts">
  // Phase 7b MOCKUP marker: an amber note on every mocked block, so a made-up value is never mistaken
  // for a real one.
  import { FlaskConical } from '@lucide/svelte';
  import { cn } from '$lib/utils';

  let { text, class: className = '' }: { text: string; class?: string } = $props();
</script>

<p
  class={cn(
    'flex items-start gap-2 rounded-md border border-dashed border-amber-500/60 bg-amber-500/10 px-3 py-2 font-sans text-xs text-amber-800 dark:text-amber-200',
    className
  )}
>
  <FlaskConical size={14} class="mt-px shrink-0" />
  <span>{text}</span>
</p>
