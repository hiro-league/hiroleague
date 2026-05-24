<script lang="ts">
  /**
   * Anchor-based action button for page headers (variant 5 in
   * `docs/admin-frontend-refactor-plan.md` §2.2).
   *
   * Renders a real `<a href>` styled like a Button so middle-click,
   * Cmd-click, copy-link, and right-click context menus work. Use whenever
   * a page-header action navigates to another page — never
   * `<Button onclick={() => goto(...)}>` for those.
   */
  import type { Component, Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Variant = 'default' | 'secondary' | 'outline' | 'ghost' | 'destructive';
  type Size = 'default' | 'sm' | 'icon';

  type Props = {
    href: string;
    variant?: Variant;
    size?: Size;
    class?: string;
    /** Optional Lucide icon component rendered before the label. */
    icon?: Component<{ size?: number; class?: string }>;
    target?: string;
    rel?: string;
    ariaLabel?: string;
    title?: string;
    children?: Snippet;
  };

  let {
    href,
    variant = 'outline',
    size = 'default',
    class: className = '',
    icon: Icon,
    target,
    rel,
    ariaLabel,
    title,
    children
  }: Props = $props();

  const variants: Record<Variant, string> = {
    default: 'bg-primary text-primary-foreground shadow-xs hover:bg-primary/90',
    secondary: 'bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80',
    outline:
      'border border-input bg-background shadow-xs hover:bg-accent hover:text-accent-foreground',
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

<a
  class={cn(
    'inline-flex shrink-0 items-center justify-center gap-2 rounded-md font-sans text-sm font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring',
    variants[variant],
    sizes[size],
    className
  )}
  {href}
  {target}
  {rel}
  aria-label={ariaLabel}
  {title}
>
  {#if Icon}
    <Icon size={16} />
  {/if}
  {@render children?.()}
</a>
