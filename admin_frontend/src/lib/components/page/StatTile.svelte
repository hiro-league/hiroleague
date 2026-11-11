<script lang="ts">
  import type { Component, Snippet } from 'svelte';
  import { ArrowRight } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import { catVar } from '$kit/ui/category';

  /** `primary`, or a category number (1 … 8) for a tile's own colour. */
  type Accent = 'primary' | number;

  let {
    href,
    title,
    subtitle,
    icon: Icon,
    accent = 'primary',
    children
  }: {
    href: string;
    title: string;
    subtitle: string;
    icon: Component<{ size?: number }>;
    accent?: Accent;
    children?: Snippet;
  } = $props();

  const tone = $derived(accent === 'primary' ? 'var(--primary)' : catVar(accent));
</script>

<a
  class={cn(
    'group grid min-h-36 gap-3 rounded-lg border bg-card p-4 shadow-sm transition-colors hover:border-(--tile)/50',
    accent === 'primary' ? 'hover:bg-secondary/20' : 'hover:bg-(--tile)/5'
  )}
  style:--tile={tone}
  {href}
>
  <div class="flex items-start justify-between gap-3">
    <div class="flex items-center gap-3">
      <span class="rounded-full bg-(--tile)/15 p-2.5 text-(--tile)">
        <Icon size={20} />
      </span>
      <div>
        <h3 class="font-sans text-base font-semibold">{title}</h3>
        <span class="font-sans text-xs font-semibold text-muted-foreground">{subtitle}</span>
      </div>
    </div>
    <ArrowRight
      class="mt-1 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-(--tile)"
      size={18}
    />
  </div>

  {#if children}
    <div class="grid gap-3">
      {@render children()}
    </div>
  {/if}
</a>
