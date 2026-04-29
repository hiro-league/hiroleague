<script lang="ts">
  import type { HTMLAttributes } from 'svelte/elements';
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Variant = 'default' | 'secondary' | 'success' | 'warning' | 'destructive' | 'outline';

  let {
    class: className = '',
    variant = 'default',
    children,
    ...rest
  }: HTMLAttributes<HTMLSpanElement> & { variant?: Variant; children?: Snippet } = $props();

  const variants: Record<Variant, string> = {
    default: 'bg-primary text-primary-foreground',
    secondary: 'bg-secondary text-secondary-foreground',
    success: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
    warning: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
    destructive: 'bg-destructive/15 text-destructive',
    outline: 'border border-border text-muted-foreground'
  };
</script>

<span
  class={cn(
    'inline-flex w-fit items-center rounded-full px-2.5 py-0.5 font-sans text-xs font-semibold',
    variants[variant],
    className
  )}
  {...rest}
>
  {@render children?.()}
</span>
