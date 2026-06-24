<script lang="ts">
  import type { Component, Snippet } from 'svelte';
  import { ArrowRight } from '@lucide/svelte';
  import { cn } from '$lib/utils';

  type Accent = 'primary' | 'emerald' | 'cyan';

  const accentStyles: Record<
    Accent,
    { card: string; icon: string; arrow: string }
  > = {
    primary: {
      card: 'hover:border-primary/50 hover:bg-secondary/20',
      icon: 'bg-primary/15 text-primary',
      arrow: 'group-hover:text-primary'
    },
    emerald: {
      card: 'hover:border-emerald-500/50 hover:bg-emerald-500/5',
      icon: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
      arrow: 'group-hover:text-emerald-700 dark:group-hover:text-emerald-300'
    },
    cyan: {
      card: 'hover:border-cyan-500/50 hover:bg-cyan-500/5',
      icon: 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300',
      arrow: 'group-hover:text-cyan-700 dark:group-hover:text-cyan-300'
    }
  };

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

  const styles = $derived(accentStyles[accent]);
</script>

<a
  class={cn(
    'group grid min-h-36 gap-3 rounded-lg border bg-card p-4 shadow-sm transition-colors',
    styles.card
  )}
  {href}
>
  <div class="flex items-start justify-between gap-3">
    <div class="flex items-center gap-3">
      <span class={cn('rounded-full p-2.5', styles.icon)}>
        <Icon size={20} />
      </span>
      <div>
        <h3 class="font-sans text-base font-semibold">{title}</h3>
        <span class="font-sans text-xs font-semibold text-muted-foreground">{subtitle}</span>
      </div>
    </div>
    <ArrowRight
      class={cn('mt-1 text-muted-foreground transition-transform group-hover:translate-x-0.5', styles.arrow)}
      size={18}
    />
  </div>

  {#if children}
    <div class="grid gap-3">
      {@render children()}
    </div>
  {/if}
</a>
