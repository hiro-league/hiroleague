<script lang="ts" generics="TId extends string">
  /**
   * Generic page-level tab strip.
   *
   * - `kind: 'pane'` tab descriptors render as buttons and call `onSelect`.
   * - `kind: 'route'` descriptors render as anchors (`<a href>`) so the
   *   browser handles middle-click / copy-link / right-click — never a
   *   `<Button onclick={goto()}>` shape.
   * - A `recordTab` snippet slot is appended after the static tabs (used by
   *   Characters' "open record" Detail chip — see `AdminRecordTabChip`).
   *
   * Second-level underline navigation uses `<AdminSubtabStrip>` (Preferences
   * sections, Graph runs ledger strip). Dynamic per-record subtabs stay in an
   * `extraTabs` snippet until a second consumer needs the same pattern.
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import { ADMIN_TABLIST_SHELL } from '$lib/styling/admin-tokens';
  import AdminTabButton from './AdminTabButton.svelte';
  import type { AdminTabDescriptor } from './tab-types';

  type Props = {
    ariaLabel: string;
    tabs: readonly AdminTabDescriptor<TId>[];
    /** Id of the currently active pane tab (ignored for `kind: 'route'`). */
    active: TId;
    /** Called when a pane tab is clicked. Route tabs navigate via their `href`. */
    onSelect?: (id: TId) => void;
    /** Optional extra classes appended to the tab strip wrapper. */
    class?: string;
    /**
     * Optional trailing chip / dynamic tab (e.g. Characters' "open record"
     * Detail chip). Rendered inside the tab strip after the fixed tabs.
     */
    recordTab?: Snippet;
  };

  let {
    ariaLabel,
    tabs,
    active,
    onSelect,
    class: className,
    recordTab
  }: Props = $props();
</script>

<div class={cn(ADMIN_TABLIST_SHELL, className)} role="tablist" aria-label={ariaLabel}>
  {#each tabs as tab (tab.id)}
    {#if tab.kind === 'route'}
      <AdminTabButton
        label={tab.label}
        icon={tab.icon}
        active={tab.id === active}
        href={tab.href}
        disabled={tab.disabled}
        ariaLabel={tab.ariaLabel}
        htmlId={tab.htmlId}
        ariaControls={tab.ariaControls}
      />
    {:else}
      <AdminTabButton
        label={tab.label}
        icon={tab.icon}
        active={tab.id === active}
        disabled={tab.disabled}
        ariaLabel={tab.ariaLabel}
        htmlId={tab.htmlId}
        ariaControls={tab.ariaControls}
        onclick={() => onSelect?.(tab.id)}
      />
    {/if}
  {/each}
  {#if recordTab}
    {@render recordTab()}
  {/if}
</div>
