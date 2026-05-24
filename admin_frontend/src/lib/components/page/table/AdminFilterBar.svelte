<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Props = {
    class?: string;
    children?: Snippet;
  };

  let { class: className, children }: Props = $props();
</script>

<div class={cn('flex flex-wrap items-end gap-3', className)}>
  {@render children?.()}
</div>
