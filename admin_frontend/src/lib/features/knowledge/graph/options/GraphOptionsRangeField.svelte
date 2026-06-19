<script lang="ts">
  import GraphRangeSlider from '../GraphRangeSlider.svelte';
  import GraphOptionsResetDot from './GraphOptionsResetDot.svelte';

  let {
    title,
    dirty = false,
    onReset,
    min,
    max,
    step,
    lo,
    hi,
    format,
    onChange,
    leftLabel,
    rightLabel
  }: {
    title: string;
    dirty?: boolean;
    onReset: () => void;
    min: number;
    max: number;
    step: number;
    lo: number;
    hi: number;
    format: (v: number) => string;
    onChange: (lo: number, hi: number) => void;
    leftLabel?: string;
    rightLabel?: string;
  } = $props();
</script>

<div>
  <div class="mb-1 flex items-center text-xs">
    <span class="flex items-center font-medium">
      {title}
      <GraphOptionsResetDot dirty={dirty} onReset={onReset} />
    </span>
  </div>
  <GraphRangeSlider min={min} max={max} step={step} value={[lo, hi]} format={format} onChange={onChange} />
  {#if leftLabel && rightLabel}
    <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
      <span>{leftLabel}</span><span>{rightLabel}</span>
    </div>
  {/if}
</div>
