<script lang="ts">
  import { X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import { fieldLabel, formatLedgerField } from './graph-runs-pure';

  let {
    row,
    fields,
    onClose
  }: {
    row: GraphLedgerRow;
    fields: readonly (keyof GraphLedgerRow)[];
    onClose: () => void;
  } = $props();

  const detailRows: readonly (readonly (keyof GraphLedgerRow)[])[] = [
    ['status', 'elapsed_ms'],
    ['chat_channel_id', 'device_id'],
    ['provider'],
    ['model'],
    ['input_preview'],
    ['output_preview'],
    ['user_id', 'character_id'],
    ['tts_chars', 'tts_text_tokens'],
    ['tts_audio_tokens', 'tts_audio_seconds'],
    ['stt_audio_seconds', 'stt_audio_tokens'],
    ['run_id'],
    ['inbound_id'],
    ['input_tokens', 'output_tokens'],
    ['cached_input_tokens', 'reasoning_tokens'],
    ['pricing_version', 'decision_kind'],
    ['decision_detail'],
    ['error_code'],
    ['row_kind'],
    ['id'],
    ['ts'],
    ['node_attempt', 'branch_index']
  ];
  const headerStep = $derived(formatLedgerField('step_index', row));
  const headerNode = $derived(String(row.node ?? '').trim() || '-');
  const headerCost = $derived(formatLedgerField('cost_usd', row));

  function shouldWrapField(field: keyof GraphLedgerRow): boolean {
    return (
      field === 'input_preview' ||
      field === 'output_preview' ||
      field === 'decision_detail' ||
      field === 'error_code' ||
      field === 'run_id' ||
      field === 'inbound_id' ||
      field === 'id' ||
      field === 'model'
    );
  }
</script>

<aside
  class="node-detail-panel flex min-h-0 flex-col overflow-hidden rounded-md border bg-card/80"
  aria-label="Graph run node details"
>
  <div class="flex min-w-0 items-center justify-between gap-3 border-b px-3 py-2.5">
    <h3 class="node-detail-title">
      <span class="accent-text-gradient">Step {headerStep}</span>
      <span class="node-detail-title-node" title={headerNode}>{headerNode}</span>
      <span class="node-detail-title-cost" title="Cost">{headerCost}</span>
    </h3>
    <Button variant="ghost" size="icon" class="size-8 shrink-0" aria-label="Close node details" onclick={onClose}>
      <X size={15} />
    </Button>
  </div>

  <div class="min-h-0 flex-1 overflow-auto p-3 font-sans">
    <dl class="node-detail-rows">
      {#each detailRows as rowFields, rowIndex (rowIndex)}
        <div class="node-detail-row" class:node-detail-row--single={rowFields.length === 1}>
          {#each rowFields as field (field)}
            <div class="node-detail-field" class:node-detail-field--single={rowFields.length === 1}>
            <dt title={field}>{fieldLabel(field)}</dt>
            <dd class:node-detail-field__value--wrap={shouldWrapField(field)}>
              {formatLedgerField(field, row)}
            </dd>
          </div>
          {/each}
        </div>
      {/each}
    </dl>
  </div>
</aside>

<style>
  .node-detail-title {
    display: flex;
    min-width: 0;
    flex: 1 1 auto;
    align-items: center;
    gap: 8px;
    margin: 0;
    font-family: var(--font-sans, ui-sans-serif, system-ui, sans-serif);
    font-size: 13px;
    font-weight: 700;
    line-height: 1.35;
  }

  .node-detail-title-node {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
    font-size: 12px;
    font-weight: 500;
    color: var(--foreground, #0f172a);
  }

  .node-detail-title-cost {
    flex: 0 0 auto;
    border-radius: 999px;
    border: 1px solid var(--border, #e2e8f0);
    background: var(--muted, #f1f5f9);
    padding: 1px 7px;
    color: var(--muted-foreground, #64748b);
  }

  .node-detail-rows {
    display: grid;
    gap: 6px;
    margin: 0;
  }

  .node-detail-row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    min-width: 0;
  }

  .node-detail-row--single {
    grid-template-columns: minmax(0, 1fr);
  }

  .node-detail-field {
    min-width: 0;
    border: 1px solid var(--border, #e2e8f0);
    border-radius: 6px;
    background: color-mix(in srgb, var(--muted, #f1f5f9) 42%, transparent);
    padding: 7px 8px;
  }

  .node-detail-field dt,
  .node-detail-field dd {
    min-width: 0;
    margin: 0;
  }

  .node-detail-field dt {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted-foreground, #64748b);
    font-size: 10px;
    font-weight: 800;
    line-height: 1.2;
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }

  .node-detail-field dd {
    margin-top: 4px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.25;
    color: var(--foreground, #0f172a);
  }

  .node-detail-field__value--wrap {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
</style>
