<script lang="ts">
  import type { Component, Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Props = {
    title: string;
    icon: Component<{ size?: number }>;
    value: string;
    caption?: string;
    detail?: string;
    nested?: boolean;
    children?: Snippet;
  };

  let { title, icon: Icon, value, caption, detail, nested = false, children }: Props = $props();
</script>

<article
  class={cn(
    'grid min-w-0 gap-[0.65rem] rounded-md border bg-card p-4 shadow-sm',
    nested && 'bg-[color-mix(in_srgb,var(--card)_85%,var(--background))] shadow-none'
  )}
>
  <div class="flex min-w-0 items-center gap-2.5 text-muted-foreground">
    <Icon size={19} />
    <h3 class="min-w-0 truncate font-sans text-[0.95rem] font-bold text-foreground">{title}</h3>
  </div>
  <strong class="min-w-0 [overflow-wrap:anywhere] font-sans text-[clamp(1.75rem,4vw,2.25rem)] leading-[1.05]">
    {value}
  </strong>
  {#if caption}
    <span class="min-w-0 [overflow-wrap:anywhere] font-sans text-[0.82rem] text-muted-foreground">
      {caption}
    </span>
  {/if}
  {#if detail}
    <span class="min-w-0 [overflow-wrap:anywhere] font-sans text-[0.82rem] text-muted-foreground">
      {detail}
    </span>
  {/if}
  {@render children?.()}
</article>
