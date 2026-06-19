<script lang="ts">
  // Extracted (admin-ui refactor): date range control shared by the Filters section's
  // "Valid date" / "Creation date" blocks, which were identical apart from labels and
  // the model getter/setter. Falls back to a hint when no facts carry the date.
  import GraphRangeSlider from '../GraphRangeSlider.svelte';
  import GraphOptionsResetDot from './GraphOptionsResetDot.svelte';

  let {
    title,
    dirty = false,
    onReset,
    span,
    value,
    step,
    format,
    onChange,
    emptyText
  }: {
    title: string;
    dirty?: boolean;
    onReset: () => void;
    span: { lo: number; hi: number } | null;
    value: [number, number];
    step: number;
    format: (v: number) => string;
    onChange: (lo: number, hi: number) => void;
    emptyText: string;
  } = $props();
</script>

<div>
  <div class="mb-1 flex items-center text-xs">
    <span class="flex items-center font-medium">
      {title}
      <GraphOptionsResetDot dirty={dirty} onReset={onReset} />
    </span>
  </div>
  {#if span}
    <GraphRangeSlider min={span.lo} max={span.hi} {step} {value} {format} {onChange} />
  {:else}
    <p class="text-[10px] text-muted-foreground">{emptyText}</p>
  {/if}
</div>
