<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Variant = 'default' | 'secondary' | 'outline' | 'ghost' | 'destructive';
  type Size = 'default' | 'sm' | 'icon';

  let {
    class: className = '',
    variant = 'default',
    size = 'default',
    children,
    type = 'button',
    ...rest
  }: HTMLButtonAttributes & { variant?: Variant; size?: Size; children?: Snippet } = $props();

  const variants: Record<Variant, string> = {
    default: 'bg-primary text-primary-foreground shadow-xs hover:bg-primary/90',
    secondary: 'bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80',
    outline: 'border border-input bg-background shadow-xs hover:bg-accent hover:text-accent-foreground',
    ghost: 'hover:bg-accent hover:text-accent-foreground',
    destructive:
      'bg-destructive text-white shadow-xs hover:bg-destructive/90 focus-visible:ring-destructive/20'
  };

  const sizes: Record<Size, string> = {
    default: 'h-9 px-4 py-2',
    sm: 'h-8 px-3 text-xs',
    icon: 'size-9'
  };
</script>

<button
  class={cn(
    'inline-flex shrink-0 items-center justify-center gap-2 rounded-md font-sans text-sm font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
    variants[variant],
    sizes[size],
    className
  )}
  {type}
  {...rest}
>
  {@render children?.()}
</button>
