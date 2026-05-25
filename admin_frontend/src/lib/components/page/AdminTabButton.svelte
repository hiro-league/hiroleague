<script lang="ts">
  /**
   * Single tab inside an `<AdminTabStrip>`. Renders as a `<button role="tab">`
   * for `kind: 'pane'` and as `<a role="tab">` for `kind: 'route'`.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import { cnAdminTab } from '$lib/styling/admin-tokens';
  import type { AdminTabIcon } from './tab-types';

  type Props = {
    label: string;
    active: boolean;
    /** Optional Lucide icon rendered before the label or `children` snippet. */
    icon?: AdminTabIcon;
    /** When set, renders an `<a href>` instead of a `<button>` (route tab). */
    href?: string;
    disabled?: boolean;
    ariaControls?: string;
    ariaLabel?: string;
    /** DOM `id` for the rendered tab element. */
    htmlId?: string;
    /** Click handler for pane tabs; ignored for route tabs (the anchor handles it). */
    onclick?: () => void;
    /** Optional custom content; defaults to `label`. */
    children?: Snippet;
  };

  let {
    label,
    active,
    icon: Icon,
    href,
    disabled = false,
    ariaControls,
    ariaLabel,
    htmlId,
    onclick,
    children
  }: Props = $props();

  // Base shape mirrors the existing tab strip (Button "secondary"/"ghost") so
  // the visual is identical to today's hand-rolled strips.
  const base =
    'inline-flex shrink-0 items-center justify-center gap-2 rounded-md px-4 py-2 font-sans text-sm font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50';
  const activeStyle = 'bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80';
</script>

{#if href}
  <a
    class={cn(base, active ? activeStyle : '', cnAdminTab(active))}
    id={htmlId}
    {href}
    role="tab"
    aria-selected={active}
    aria-controls={ariaControls}
    aria-label={ariaLabel}
    aria-disabled={disabled || undefined}
    tabindex={disabled ? -1 : 0}
  >
    {#if Icon}
      <Icon size={16} class="shrink-0" />
    {/if}
    {#if children}{@render children()}{:else}{label}{/if}
  </a>
{:else}
  <button
    type="button"
    class={cn(base, active ? activeStyle : '', cnAdminTab(active))}
    id={htmlId}
    role="tab"
    aria-selected={active}
    aria-controls={ariaControls}
    aria-label={ariaLabel}
    {disabled}
    {onclick}
  >
    {#if Icon}
      <Icon size={16} class="shrink-0" />
    {/if}
    {#if children}{@render children()}{:else}{label}{/if}
  </button>
{/if}
