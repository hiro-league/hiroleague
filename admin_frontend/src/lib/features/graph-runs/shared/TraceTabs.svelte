<script lang="ts">
  // The tab strip shared by both trace dialogs. Two variants:
  //  • 'subtabs' (ingest pipeline phases) — sticky, count always shown, muted count.
  //  • 'lanes'   (retrieval lanes)        — bordered, count shown only when populated, primary count.
  // `count` is a pre-formatted string (or null to hide) so the caller controls "(3)" vs "3".
  export type TraceTab = { key: string; label: string; count?: string | null };

  let {
    tabs,
    active,
    onSelect,
    ariaLabel,
    variant = 'lanes',
    countTone = 'primary'
  }: {
    tabs: TraceTab[];
    active: string;
    onSelect: (key: string) => void;
    ariaLabel: string;
    variant?: 'subtabs' | 'lanes';
    countTone?: 'muted' | 'primary';
  } = $props();
</script>

<div
  class="trace-tabs"
  class:trace-tabs--subtabs={variant === 'subtabs'}
  class:trace-tabs--lanes={variant === 'lanes'}
  role="tablist"
  aria-label={ariaLabel}
>
  {#each tabs as tab (tab.key)}
    <button
      type="button"
      role="tab"
      class="trace-tab"
      class:trace-tab--subtabs={variant === 'subtabs'}
      class:trace-tab--lanes={variant === 'lanes'}
      class:trace-tab--active={active === tab.key}
      aria-selected={active === tab.key}
      onclick={() => onSelect(tab.key)}
    >
      {tab.label}
      {#if tab.count != null}
        <span class="trace-tab__count" class:trace-tab__count--muted={countTone === 'muted'}>
          {tab.count}
        </span>
      {/if}
    </button>
  {/each}
</div>

<style>
  .trace-tabs {
    display: flex;
    gap: 4px;
  }

  .trace-tabs--lanes {
    border-bottom: 1px solid color-mix(in srgb, var(--muted-foreground) 22%, transparent);
  }

  /* Pipeline phase sub-tabs sit in the scroll body (not the header) with a divider under. */
  .trace-tabs--subtabs {
    flex: none;
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--background);
    border-bottom: 1px solid color-mix(in srgb, var(--muted-foreground) 18%, transparent);
    padding-bottom: 2px;
  }

  .trace-tab {
    appearance: none;
    border: none;
    background: transparent;
    border-bottom: 2px solid transparent;
    font-size: 13px;
    font-weight: 600;
    color: var(--muted-foreground);
    cursor: pointer;
  }

  .trace-tab--lanes {
    padding: 8px 14px;
    margin-bottom: -1px;
  }

  .trace-tab--subtabs {
    padding: 6px 12px;
  }

  .trace-tab:hover {
    color: var(--foreground);
  }

  .trace-tab--active {
    color: var(--foreground);
    border-bottom-color: var(--primary);
  }

  .trace-tab:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: -2px;
    border-radius: 4px;
  }

  /* Default (retrieval): primary, slightly larger/bolder. `--muted` (ingest): muted, smaller. */
  .trace-tab__count {
    margin-left: 4px;
    font-size: 11px;
    font-weight: 700;
    color: var(--primary);
    font-variant-numeric: tabular-nums;
  }

  .trace-tab__count--muted {
    margin-left: 5px;
    font-size: 10px;
    font-weight: 600;
    color: var(--muted-foreground);
  }
</style>
