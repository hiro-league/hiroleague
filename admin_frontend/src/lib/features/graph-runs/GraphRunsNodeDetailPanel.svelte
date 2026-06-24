<script lang="ts">
  import DetailFieldGrid, {
    type DetailFieldRow
  } from '$lib/components/page/DetailFieldGrid.svelte';
  import DetailPanelShell from '$lib/components/page/DetailPanelShell.svelte';
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import { fieldLabel, formatLedgerField, previewMultiline } from './graph-runs-pure';

  let {
    row,
    fields,
    onClose
  }: {
    row: GraphLedgerRow;
    fields: readonly (keyof GraphLedgerRow)[];
    onClose: () => void;
  } = $props();

  const detailRowFields: readonly (readonly (keyof GraphLedgerRow)[])[] = [
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

  function isPreviewField(field: keyof GraphLedgerRow): boolean {
    return field === 'input_preview' || field === 'output_preview';
  }

  const gridRows = $derived.by((): DetailFieldRow[] =>
    detailRowFields.map((rowFields) =>
      rowFields.map((field) => {
        const preview = isPreviewField(field);
        const formatted = formatLedgerField(field, row);
        return {
          label: fieldLabel(field),
          labelTitle: field,
          value: preview ? previewMultiline(formatted) : formatted,
          valueTitle: preview ? previewMultiline(formatted) : undefined,
          wrap: shouldWrapField(field),
          preview
        };
      })
    )
  );
</script>

<DetailPanelShell
  ariaLabel="Graph run node details"
  class="bg-card/80"
  closeLabel="Close node details"
  {onClose}
>
  {#snippet title()}
    <h3 class="node-detail-title">
      <span class="accent-text-gradient">Step {headerStep}</span>
      <span class="node-detail-title-node" title={headerNode}>{headerNode}</span>
      <span class="node-detail-title-cost" title="Cost">{headerCost}</span>
    </h3>
  {/snippet}

  {#snippet children()}
    <DetailFieldGrid rows={gridRows} />
  {/snippet}
</DetailPanelShell>

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
</style>
