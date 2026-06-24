<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { page } from '$app/state';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import AdminMasterDetail from '$lib/components/page/table/AdminMasterDetail.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineWarningAlert from '$lib/ui/InlineWarningAlert.svelte';
  import type { ToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import type { LogsPageController } from './state/logs-controller.svelte';
  import type { LogsPreferences } from '$lib/preferences/logs-preferences.svelte';
  import LogsDetailPanel from './LogsDetailPanel.svelte';
  import LogsFiltersPanel from './LogsFiltersPanel.svelte';
  import LogsTablePanel from './LogsTablePanel.svelte';
  import LogsToolbar from './LogsToolbar.svelte';
  import { setupLogsPageRuntime } from './shared/logs-page-lifecycle';
  import type { RenderLogRow } from './shared/logs-ui';

  // Portable logs body. The page header chrome (folder button, counts subtitle,
  // filter collapse chevron) lives in the host `LogsPage.svelte` because Graph
  // runs shares that header as the Logs page's second tab. `ctrl`/`prefs`/`notify`
  // are owned by the host and passed down so both header and body stay in sync.
  let {
    ctrl,
    prefs,
    notify
  }: { ctrl: LogsPageController; prefs: LogsPreferences; notify: ToastNotifier['notify'] } = $props();

  // Auto-follow new logs only while pinned to the very top (newest-first feed); once
  // the user scrolls down to read, stop yanking them back to the top.
  let atTop = $state(true);
  let tableScroller = $state<HTMLDivElement | null>(null);
  let clearLogsConfirmOpen = $state(false);

  // Sticky offsets clear the shell bar (4rem) + the sticky page header + the sticky
  // filter toolbar (heights published as CSS vars). Collapsing now only removes the
  // second (secondary-filters) line while the first toolbar line stays visible, so the
  // toolbar always keeps a real, nonzero height — removing one row reliably re-fires
  // ResizeObserver, so we can read the published var directly without gating on the flag.
  const tableStickyTop = $derived(
    `calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px))`
  );
  const detailStickyTop = $derived(`calc(${tableStickyTop} + 0.75rem)`);
  // Fixed height (not just max-height) so the panel always fills the visible page
  // area even with little data; its inner body scrolls when content overflows.
  const detailHeight = $derived(`calc(100vh - ${tableStickyTop} - 1.5rem)`);

  function selectRow(row: RenderLogRow) {
    ctrl.setActiveRow(row);
    tableScroller?.focus();
  }

  function openRowDetails(row: RenderLogRow) {
    ctrl.setActiveRow(row);
    prefs.detailPanelOpen = true;
    tableScroller?.focus();
  }

  function requestClearLogs() {
    clearLogsConfirmOpen = true;
  }

  function confirmClearLogs() {
    clearLogsConfirmOpen = false;
    void ctrl.clearAllLogs();
  }

  $effect(() => {
    ctrl.rows.length;
    ctrl.visibleRows.length;
    prefs.sortColumn;
    prefs.sortDir;
    if (!ctrl.initialized || !atTop) return;
    void tick().then(() => {
      if (typeof window !== 'undefined') window.scrollTo({ top: 0 });
    });
  });

  onMount(() => {
    const onScroll = () => (atTop = window.scrollY <= 4);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  });

  onMount(() =>
    setupLogsPageRuntime({
      prefs,
      ctrl,
      urlMsgId: page.url.searchParams.get('msg_id')
    })
  );
</script>

<!-- Controls live on their own sticky line below the shared page header. The first
     line (level / search / pause / time window / actions) always stays mounted so it
     remains visible and sticky even when filters are collapsed; only the second line
     (secondary filters) collapses. The collapse chevron sits at the far right of the
     first line and targets the second line's region via aria-controls. -->
<AdminPageStickyToolbar>
  <LogsToolbar {prefs} {ctrl} onRequestClearLogs={requestClearLogs}>
    {#snippet filters()}
      <LogsFiltersPanel {prefs} {ctrl} />
    {/snippet}
  </LogsToolbar>
</AdminPageStickyToolbar>

{#if ctrl.error}
  <InlineDestructiveAlert message={ctrl.error} class="px-3 py-2 text-sm" />
{:else if ctrl.pollError}
  <InlineWarningAlert message={ctrl.pollError} class="px-3 py-2 text-sm" />
{/if}

<AdminMasterDetail bind:detailOpen={prefs.detailPanelOpen} scroll="page">
  {#snippet list()}
    <LogsTablePanel
      {ctrl}
      detailPanelOpen={prefs.detailPanelOpen}
      stickyHeadTop={tableStickyTop}
      sortColumn={prefs.sortColumn}
      sortDir={prefs.sortDir}
      onToggleSort={(col) => prefs.toggleSortColumn(col)}
      bind:scroller={tableScroller}
      onSelectRow={selectRow}
      onOpenRowDetails={openRowDetails}
      onTableKeydown={(event) => ctrl.handleTableKeydown(event, () => tableScroller)}
      onFilterToMessage={ctrl.filterToMessage}
    />
  {/snippet}
  {#snippet detail()}
    <!-- Sticky so the detail stays in view while the table scrolls the document. -->
    <LogsDetailPanel
      activeRow={ctrl.activeRow}
      onClose={() => (prefs.detailPanelOpen = false)}
      onNotify={notify}
      class="sticky self-start z-20"
      style="top: {detailStickyTop}; height: {detailHeight};"
    />
  {/snippet}
</AdminMasterDetail>

<Dialog.Root
  open={clearLogsConfirmOpen}
  onOpenChange={(next) => {
    if (!next && !ctrl.clearingLogs) clearLogsConfirmOpen = false;
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Clear all logs?</Dialog.Title>
      <Dialog.Description>This truncates workspace, gateway, and stderr log files.</Dialog.Description>
    </Dialog.Header>
    <p class="font-sans text-sm text-muted-foreground">This action cannot be undone.</p>
    <Dialog.Footer>
      <Button variant="outline" disabled={ctrl.clearingLogs} onclick={() => (clearLogsConfirmOpen = false)}>
        Cancel
      </Button>
      <Button variant="destructive" disabled={ctrl.clearingLogs} onclick={confirmClearLogs}>
        Clear logs
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
