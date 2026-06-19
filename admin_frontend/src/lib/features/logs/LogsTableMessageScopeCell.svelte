<script lang="ts">
  import { MessageSquare } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import type { RenderLogRow } from './shared/logs-ui';

  type Props = {
    row: RenderLogRow;
    msgOrd: number | null;
    chipAlt: boolean;
    onFilterToMessage: (msgId: string, event: MouseEvent) => void;
  };

  let { row, msgOrd, chipAlt, onFilterToMessage }: Props = $props();
</script>

{#if row.scope_msg_id}
  <div class="flex items-center justify-center gap-0.5">
    {#if msgOrd != null}
      <!-- Chip color alternates when the message # changes vs the previous scoped row (table order). -->
      <span
        class={cn(
          'inline-flex min-h-4 min-w-[1rem] shrink-0 items-center justify-center rounded px-1 text-[0.6rem] font-semibold tabular-nums leading-none',
          chipAlt
            ? 'border border-border/70 bg-muted text-foreground'
            : 'border border-primary/35 bg-primary/15 text-primary'
        )}
        title="Message #{msgOrd} in this session (stable while the logs page is open)"
      >
        {msgOrd}
      </span>
    {/if}
    <button
      type="button"
      class="inline-grid shrink-0 place-items-center rounded-md p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
      title={row.scope_text_preview?.trim()
        ? `Message text: ${row.scope_text_preview} — Filter to this message`
        : 'Filter to this message'}
      onclick={(e) => onFilterToMessage(row.scope_msg_id!, e)}
      ondblclick={(e) => e.stopPropagation()}
    >
      <MessageSquare size={14} strokeWidth={2} aria-hidden="true" />
      <span class="sr-only">
        Filter to message{msgOrd != null ? ` ${msgOrd}` : ''}
      </span>
    </button>
  </div>
{/if}
