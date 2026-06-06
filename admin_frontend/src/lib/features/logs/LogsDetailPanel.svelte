<script lang="ts">
  import { Copy, X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { Notify } from '$lib/features/server/types';
  import LogExtraSegments from './LogExtraSegments.svelte';
  import { LOGS_DETAIL_PANEL_ID } from './shared/logs-a11y';
  import { logLevelTextClass, logModuleTextClass } from './shared/logs-classes';
  import LogLevelIcon from './shared/LogLevelIcon.svelte';
  import LogRowSourceIcon from './shared/LogRowSourceIcon.svelte';
  import { cn } from '$lib/utils';
  import {
    formatLogDetailsClipboardText,
    logRowSourceLabel,
    type RenderLogRow
  } from './shared/logs-ui';

  type Props = {
    activeRow: RenderLogRow | null;
    onClose: () => void;
    onNotify: Notify;
    /** Extra classes (page uses this to make the panel sticky under page chrome). */
    class?: string;
    /** Inline style (page sets sticky `top` + `max-height` from chrome height vars). */
    style?: string;
  };

  let { activeRow, onClose, onNotify, class: className, style }: Props = $props();

  async function copyLogDetailsToClipboard() {
    const row = activeRow;
    if (!row) return;
    try {
      await navigator.clipboard.writeText(formatLogDetailsClipboardText(row));
      onNotify('success', 'Log details copied to clipboard.');
    } catch (err) {
      onNotify(
        'error',
        err instanceof Error ? err.message : 'Could not copy log details.'
      );
    }
  }
</script>

<aside
  id={LOGS_DETAIL_PANEL_ID}
  class={cn('flex min-h-0 flex-col overflow-hidden rounded-md border bg-card', className)}
  {style}
  aria-label="Log line details"
>
  <div
    class="flex min-w-0 items-center justify-between gap-3 border-b px-3 py-2.5"
  >
    <h3
      class="min-w-0 flex-1 truncate font-sans text-sm font-semibold leading-snug text-foreground"
    >
      <span class="accent-text-gradient">Log Details</span>
    </h3>
    <div class="flex shrink-0 items-center gap-2">
      {#if activeRow}
        <div
          class={cn(
            'flex items-center gap-1.5 text-[0.82rem]',
            logLevelTextClass(activeRow.level)
          )}
          aria-label="Log level {activeRow.level}"
        >
          <LogLevelIcon level={activeRow.level} size={15} class="shrink-0" />
          <span class="font-medium">{activeRow.level}</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          class="size-8 shrink-0"
          aria-label="Copy all log details"
          title="Copy all log details"
          onclick={() => void copyLogDetailsToClipboard()}
        >
          <Copy size={15} />
        </Button>
      {/if}
      <Button variant="ghost" size="icon" class="size-8 shrink-0" onclick={onClose}>
        <X size={15} />
      </Button>
    </div>
  </div>
  <div class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden font-sans">
    <div class="min-h-0 flex-1 overflow-auto p-3">
      {#if activeRow}
        {@const sub =
          'block text-[0.68rem] font-bold uppercase tracking-wide accent-text-gradient'}
        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-x-4 gap-y-1">
            <div class="min-w-0">
              <span class={sub}>Source</span>
              <p
                class="mt-1 flex min-w-0 items-center gap-1.5 text-[0.82rem]"
                title={activeRow.source}
              >
                <LogRowSourceIcon
                  rowSource={activeRow.source}
                  size={15}
                  class="shrink-0 text-muted-foreground"
                />
                <span class="min-w-0 truncate">{logRowSourceLabel(activeRow.source)}</span>
              </p>
            </div>
            <div class="min-w-0">
              <span class={sub}>Module</span>
              <p class="mt-1 min-w-0 truncate text-[0.82rem]" title={activeRow.module}>
                <span class={logModuleTextClass(activeRow.module)}>{activeRow.module || '—'}</span>
              </p>
            </div>
          </div>
          <div>
            <span class={sub}>Message</span>
            {#if activeRow.message_pretty}
              <pre
                class="mt-1 whitespace-pre-wrap break-words rounded-md bg-muted/70 px-[0.65rem] py-2 font-mono text-[0.82rem] leading-snug"
              >{activeRow.message_pretty}</pre>
            {:else}
              <p class="mt-1 whitespace-pre-wrap break-words text-[0.82rem]">
                {activeRow.message || '-'}
              </p>
            {/if}
          </div>
          <div>
            <span class={sub}>Device scope</span>
            <p class="mt-1 text-[0.82rem]">
              {#if activeRow.scope_device_id}
                <span class="font-mono text-xs">{activeRow.scope_device_id}</span>
              {:else}
                —
              {/if}
            </p>
          </div>
          <div>
            <span class={sub}>Request method scope</span>
            <p class="mt-1 text-[0.82rem]">
              {#if activeRow.scope_method}
                <span class="font-mono text-xs">{activeRow.scope_method}</span>
              {:else}
                —
              {/if}
            </p>
          </div>
          {#if activeRow.scope_msg_id || (activeRow.scope_text_preview ?? '').trim()}
            <div>
              <span class={sub}>Message text preview</span>
              <p
                class="mt-1 whitespace-pre-wrap break-words rounded-md bg-muted/50 px-2 py-1.5 text-[0.82rem] leading-snug text-foreground"
                title={activeRow.scope_text_preview || undefined}
              >
                {(activeRow.scope_text_preview ?? '').trim()
                  ? activeRow.scope_text_preview
                  : 'N/A'}
              </p>
            </div>
          {/if}
          <div>
            <span class={sub}>Extra</span>
            <div class="mt-1">
              <LogExtraSegments segments={activeRow.extra_segments} variant="detail" />
            </div>
          </div>
          <div>
            <span class={sub}>Message scope</span>
            <p class="mt-1 text-[0.82rem]">
              {#if activeRow.scope_msg_id}
                <span class="font-mono text-xs">{activeRow.scope_msg_id}</span>
              {:else}
                —
              {/if}
            </p>
          </div>
          <div>
            <span class={sub}>Timestamp (epoch)</span>
            <p class="mt-1 tabular-nums text-[0.82rem]">{activeRow.timestamp}</p>
          </div>
        </div>
      {:else}
        <p class="font-sans text-sm text-muted-foreground">
          Double-click a row in the table to inspect a log line.
        </p>
      {/if}
    </div>
    {#if activeRow}
      <div
        class="flex shrink-0 items-center gap-3 border-t border-border/60 bg-muted/25 px-3 py-2 font-sans text-[0.78rem] tabular-nums text-muted-foreground"
      >
        <span class="text-foreground">{activeRow.date_display}</span>
        <span
          class="h-3.5 w-px shrink-0 bg-border"
          aria-hidden="true"
        ></span>
        <span class="text-foreground">{activeRow.timestamp_display}</span>
      </div>
    {/if}
  </div>
</aside>
