<script lang="ts">
  import { cn } from '$lib/utils';

  export type DetailFieldItem = {
    label: string;
    value: string;
    /** Tooltip on the label (`dt title`). */
    labelTitle?: string;
    /** Tooltip on the value (`dd title`). */
    valueTitle?: string;
    wrap?: boolean;
    preview?: boolean;
  };

  export type DetailFieldRow = DetailFieldItem | readonly DetailFieldItem[];

  let {
    rows,
    class: className
  }: {
    rows: readonly DetailFieldRow[];
    class?: string;
  } = $props();

  function isFieldArray(row: DetailFieldRow): row is readonly DetailFieldItem[] {
    return Array.isArray(row);
  }

  function normalizeRow(row: DetailFieldRow): readonly DetailFieldItem[] {
    return isFieldArray(row) ? row : [row];
  }
</script>

<dl class={cn('detail-field-grid', className)}>
  {#each rows as row, rowIndex (rowIndex)}
    {@const fields = normalizeRow(row)}
    <div class="detail-field-row" class:detail-field-row--single={fields.length === 1}>
      {#each fields as field (field.label)}
        <div class="detail-field" class:detail-field--single={fields.length === 1}>
          <dt title={field.labelTitle ?? field.label}>{field.label}</dt>
          <dd
            class:detail-field__value--wrap={field.wrap}
            class:detail-field__value--preview={field.preview}
            title={field.valueTitle}
          >
            {field.value}
          </dd>
        </div>
      {/each}
    </div>
  {/each}
</dl>

<style>
  .detail-field-grid {
    display: grid;
    gap: 6px;
    margin: 0;
  }

  .detail-field-row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    min-width: 0;
  }

  .detail-field-row--single {
    grid-template-columns: minmax(0, 1fr);
  }

  .detail-field {
    min-width: 0;
    border: 1px solid var(--border, #e2e8f0);
    border-radius: 6px;
    background: color-mix(in srgb, var(--muted, #f1f5f9) 42%, transparent);
    padding: 7px 8px;
  }

  .detail-field dt,
  .detail-field dd {
    min-width: 0;
    margin: 0;
  }

  .detail-field dt {
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

  .detail-field dd {
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

  .detail-field dd.detail-field__value--wrap {
    overflow: visible;
    text-overflow: unset;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
    line-height: 1.4;
  }

  .detail-field dd.detail-field__value--preview {
    max-height: min(14rem, 35vh);
    overflow-x: hidden;
    overflow-y: auto;
  }
</style>
