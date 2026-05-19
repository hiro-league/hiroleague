<script lang="ts">
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import {
    fieldLabel,
    formatLedgerField,
    formatSecondsCardValue,
    formatTokenCardValue
  } from '../graph-runs-pure';

  let {
    activeRunAggregate,
    toolbarElapsedLabel,
    toolbarTotalCostLabel,
    headerFieldList
  }: {
    activeRunAggregate: GraphLedgerRow;
    toolbarElapsedLabel: string;
    toolbarTotalCostLabel: string;
    headerFieldList: readonly (keyof GraphLedgerRow)[];
  } = $props();
</script>

<div class="run-metric-card run-metric-card--preview" aria-label="Input preview card">
  <span class="run-metric-card-label">Input preview</span>
  <p class="run-preview-card-text">{activeRunAggregate.input_preview || '—'}</p>
</div>
<div class="run-metric-card run-metric-card--preview" aria-label="Output preview card">
  <span class="run-metric-card-label">Output preview</span>
  <p class="run-preview-card-text">{activeRunAggregate.output_preview || '—'}</p>
</div>
<div class="run-metric-card run-metric-card--elapsed-total" aria-label="Elapsed time and total cost">
  <div class="run-elapsed-total-inner">
    <div class="run-toolbar-elapsed" aria-label="Run duration">
      <span class="run-toolbar-metric-label">Elapsed Time</span>
      <!-- Theme colors via Tailwind `dark:` + app.css `@custom-variant dark`; avoids :global(theme) selectors. -->
      <span class="run-toolbar-elapsed-value text-emerald-600 dark:text-emerald-400">{toolbarElapsedLabel || '—'}</span>
    </div>
    <div class="run-toolbar-cost" aria-label="Total run cost">
      <span class="run-toolbar-metric-label">Total Cost</span>
      <span class="run-toolbar-cost-value text-violet-600 dark:text-violet-400">{toolbarTotalCostLabel || '—'}</span>
    </div>
  </div>
</div>
<div class="run-metric-card run-metric-card--tokens" aria-label="Token usage">
  <div class="run-token-grid">
    <div class="run-token-stat">
      <span class="run-token-stat-label">In</span>
      <span class="run-token-stat-value">{formatTokenCardValue(activeRunAggregate.input_tokens)}</span>
    </div>
    <div class="run-token-stat">
      <span class="run-token-stat-label">Cached</span>
      <span class="run-token-stat-value">{formatTokenCardValue(activeRunAggregate.cached_input_tokens)}</span>
    </div>
    <div class="run-token-stat">
      <span class="run-token-stat-label">Out</span>
      <span class="run-token-stat-value">{formatTokenCardValue(activeRunAggregate.output_tokens)}</span>
    </div>
    <div class="run-token-stat">
      <span class="run-token-stat-label">Reasoning</span>
      <span class="run-token-stat-value">{formatTokenCardValue(activeRunAggregate.reasoning_tokens)}</span>
    </div>
  </div>
</div>
<div class="run-metric-card run-metric-card--model">
  <span class="run-metric-card-label">Provider / model</span>
  <div class="run-metric-card-model">
    <span class="mono run-metric-card-model-line">{String(activeRunAggregate.provider || '').trim() || '—'}</span>
    <span class="mono run-metric-card-model-line run-metric-card-model-id"
      >{String(activeRunAggregate.model || '').trim() || '—'}</span
    >
  </div>
</div>
<div class="run-metric-card run-metric-card--speech">
  <div class="run-speech-grid" role="group" aria-label="Speech-to-text and text-to-speech usage">
    <div class="run-token-stat">
      <div class="run-metric-stat-heading">
        <abbr class="run-metric-stat-kicker" title="Speech-to-text (STT)">STT</abbr>
        <span class="run-metric-stat-desc">User audio received · transcribed</span>
      </div>
      <span class="run-token-stat-value">{formatSecondsCardValue(activeRunAggregate.stt_audio_seconds)}</span>
    </div>
    <div class="run-token-stat">
      <div class="run-metric-stat-heading">
        <abbr class="run-metric-stat-kicker" title="Text-to-speech (TTS)">TTS</abbr>
        <span class="run-metric-stat-desc">Characters synthesized into speech</span>
      </div>
      <span class="run-token-stat-value">{formatTokenCardValue(activeRunAggregate.tts_chars)}</span>
    </div>
    <div class="run-token-stat">
      <div class="run-metric-stat-heading">
        <abbr class="run-metric-stat-kicker" title="Text-to-speech (TTS) audio">TTS</abbr>
        <span class="run-metric-stat-desc">Duration of generated speech audio</span>
      </div>
      <span class="run-token-stat-value">{formatSecondsCardValue(activeRunAggregate.tts_audio_seconds)}</span>
    </div>
  </div>
</div>
<dl class="run-header-grid">
  {#each headerFieldList as field (field)}
    <dt title={field}>{fieldLabel(field)}</dt>
    <dd class="mono">{formatLedgerField(field, activeRunAggregate)}</dd>
  {/each}
</dl>

<style>
  .run-metric-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
    padding: 10px 12px;
    border: 1px solid var(--border, #e4e4e7);
    border-radius: 8px;
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 6%, transparent);
  }

  .run-metric-card.run-metric-card--preview {
    gap: 8px;
    min-height: 0;
    justify-content: flex-start;
  }

  .run-metric-card.run-metric-card--elapsed-total {
    gap: 10px;
    min-width: min(100%, 200px);
    max-width: 100%;
    align-self: stretch;
    justify-content: center;
    box-sizing: border-box;
  }

  .run-metric-card-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted-foreground, #64748b);
  }

  .run-preview-card-text {
    margin: 0;
    font-size: 13px;
    line-height: 1.35;
    color: var(--foreground, #0f172a);
    overflow-wrap: break-word;
    word-break: break-word;
    white-space: pre-wrap;
    flex: 1 1 auto;
    min-height: 0;
  }

  .run-elapsed-total-inner {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: 12px 20px;
    width: 100%;
    min-width: 0;
  }

  .run-toolbar-elapsed,
  .run-toolbar-cost {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: center;
    gap: 2px;
  }

  .run-toolbar-metric-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted-foreground, #64748b);
  }

  .run-toolbar-elapsed-value {
    font-size: 22px;
    font-weight: 600;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }

  .run-toolbar-cost-value {
    font-size: 22px;
    font-weight: 600;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }

  .run-metric-card--tokens {
    gap: 10px;
  }

  .run-metric-card--speech {
    gap: 10px;
  }

  .run-token-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 12px;
    align-items: flex-start;
  }

  .run-token-stat {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    flex: 1 1 5.25rem;
  }

  .run-token-stat-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--muted-foreground, #64748b);
  }

  .run-token-stat-value {
    font-size: 18px;
    font-weight: 600;
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
    color: var(--foreground, #0f172a);
  }

  .run-metric-card-model {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .run-metric-card-model-line {
    font-size: 12px;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .run-metric-card-model-id {
    font-size: 13px;
    font-weight: 600;
  }

  .run-speech-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px 12px;
    align-items: start;
  }

  @media (max-width: 520px) {
    .run-metric-card--speech {
      overflow-x: auto;
      padding-bottom: 4px;
    }

    .run-speech-grid {
      grid-template-columns: repeat(3, minmax(88px, 1fr));
      min-width: min(100%, 320px);
    }
  }

  .run-metric-stat-heading {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .run-metric-stat-kicker {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    text-decoration: none;
    color: var(--foreground, #0f172a);
    cursor: help;
  }

  .run-metric-stat-desc {
    font-size: 9px;
    font-weight: 500;
    line-height: 1.25;
    letter-spacing: 0.01em;
    text-transform: none;
    color: var(--muted-foreground, #64748b);
  }

  .run-header-grid {
    display: grid;
    grid-template-columns: repeat(3, max-content minmax(0, 1fr));
    gap: 6px 14px;
    margin: 0;
    padding: 12px;
    border: 1px solid var(--border, #e4e4e7);
    border-radius: 8px;
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 6%, transparent);
    font-size: 11px;
  }

  .run-header-grid dt {
    margin: 0;
    color: var(--muted-foreground, #64748b);
    font-weight: 600;
    text-transform: capitalize;
    word-break: break-word;
    grid-column: auto;
  }

  .run-header-grid dd {
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    grid-column: auto;
    color: var(--foreground, inherit);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 4.8em;
    line-height: 1.2em;
  }

  .mono {
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  }
</style>
