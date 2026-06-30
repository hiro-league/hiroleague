<script lang="ts" generics="TId extends string">
  /**
   * Second-level underline subtab strip (Preferences sections, Graph runs
   * ledger + open inspectors). Page-level pill tabs use `<AdminTabStrip>`.
   *
   * - Fixed `tabs` render as underline buttons and call `onSelect`.
   * - `extraTabs` — dynamic subtabs after the fixed set (Graph runs per-run).
   * - `toolbar` — trailing icon/actions row (refresh, collapse, …).
   */
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import { ADMIN_SUBTAB_STRIP_SHELL, ADMIN_SUBTAB_TABLIST } from '$lib/styling/admin-tokens';
  import AdminSubtabButton from './AdminSubtabButton.svelte';
  import type { AdminSubtabDescriptor } from './tab-types';

  type Props = {
    ariaLabel: string;
    tabs: readonly AdminSubtabDescriptor<TId>[];
    active: TId;
    onSelect?: (id: TId) => void;
    class?: string;
    extraTabs?: Snippet;
    toolbar?: Snippet;
  };

  let {
    ariaLabel,
    tabs,
    active,
    onSelect,
    class: className,
    extraTabs,
    toolbar
  }: Props = $props();
</script>

<div class={cn(ADMIN_SUBTAB_STRIP_SHELL, className)}>
  <div class={ADMIN_SUBTAB_TABLIST} role="tablist" aria-label={ariaLabel}>
    {#each tabs as tab (tab.id)}
      <AdminSubtabButton
        label={tab.label}
        count={tab.count}
        countText={tab.countText}
        countClass={tab.countClass}
        active={tab.id === active}
        disabled={tab.disabled}
        ariaLabel={tab.ariaLabel}
        htmlId={tab.htmlId}
        ariaControls={tab.ariaControls}
        title={tab.title}
        onclick={() => onSelect?.(tab.id)}
      />
    {/each}
    {#if extraTabs}
      {@render extraTabs()}
    {/if}
  </div>
  {#if toolbar}
    <div class="flex shrink-0 items-end gap-1 pb-px">
      {@render toolbar()}
    </div>
  {/if}
</div>
