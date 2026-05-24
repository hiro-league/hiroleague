<script lang="ts">
  /**
   * "Open record" tab chip (icon + truncated record label + X).
   *
   * Slotted into `<AdminTabStrip>` via its `recordTab` snippet. The chip is
   * created on the fly when a list row is opened into a Detail tab — see
   * Characters today, and (likely future) Catalog providers / Knowledge docs.
   */
  import type { Component, Snippet } from 'svelte';
  import { X } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import { cnAdminTab } from '$lib/styling/admin-tokens';

  type Props = {
    /** Truncated label for the chip (typically the record's display name). */
    label: string;
    active: boolean;
    /** Click handler for the chip itself (switches to the Detail tab). */
    onclick?: () => void;
    /** Click handler for the trailing X button (closes the record). */
    onClose?: () => void;
    ariaLabel?: string;
    ariaControls?: string;
    /** Optional Lucide icon component rendered before the label. */
    icon?: Component<{ size?: number; class?: string }>;
    /** Tooltip / aria-label for the close button (default: "Close"). */
    closeLabel?: string;
    /** Optional override for the label content (e.g. an icon + text). */
    children?: Snippet;
  };

  let {
    label,
    active,
    onclick,
    onClose,
    ariaLabel,
    ariaControls,
    icon: Icon,
    closeLabel = 'Close',
    children
  }: Props = $props();

  const base =
    'inline-flex shrink-0 items-center gap-2 rounded-md px-3 py-2 font-sans text-sm font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring';
  const activeStyle = 'bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80';
</script>

<div class={cn(base, active ? activeStyle : '', cnAdminTab(active))} role="tab" aria-selected={active}>
  <button
    type="button"
    class="flex min-w-0 items-center gap-2 bg-transparent outline-none focus-visible:ring-2 focus-visible:ring-ring"
    aria-label={ariaLabel ?? label}
    aria-controls={ariaControls}
    {onclick}
  >
    {#if Icon}
      <Icon size={14} class="shrink-0" />
    {/if}
    {#if children}
      {@render children()}
    {:else}
      <span class="max-w-[14rem] truncate">{label}</span>
    {/if}
  </button>
  {#if onClose}
    <button
      type="button"
      class="grid size-5 shrink-0 place-items-center rounded-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
      aria-label={closeLabel}
      title={closeLabel}
      onclick={onClose}
    >
      <X size={12} />
    </button>
  {/if}
</div>
