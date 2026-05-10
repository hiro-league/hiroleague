<script lang="ts">
  import { cn } from '$lib/utils';

  type Props = {
    message: string;
    title?: string;
    class?: string;
  };

  let { message, title, class: className }: Props = $props();
</script>

<div class={cn('rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive', className)}>
  {#if title}
    <strong class="font-sans">{title}</strong>
    <span class="block text-sm">{message}</span>
  {:else}
    <span class="font-sans text-sm">{message}</span>
  {/if}
</div>
