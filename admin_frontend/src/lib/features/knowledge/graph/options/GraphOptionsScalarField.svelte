<script lang="ts">
  // Extracted (admin-ui refactor): single-knob range control shared by the View and
  // Filters option sections. Replaces the hand-rolled <label> slider blocks that were
  // near-duplicates of one another. One-way `value` + `onInput` callback keeps the
  // writable target in the parent (parents bind to $bindable props / call the model).
  import GraphOptionsResetDot from './GraphOptionsResetDot.svelte';

  let {
    title,
    dirty = false,
    onReset,
    valueText,
    min,
    max,
    step = 1,
    value,
    onInput,
    leftLabel,
    rightLabel,
    ariaLabel
  }: {
    title: string;
    dirty?: boolean;
    onReset: () => void;
    valueText: string;
    min: number;
    max: number;
    step?: number;
    value: number;
    onInput: (v: number) => void;
    leftLabel: string;
    rightLabel: string;
    ariaLabel: string;
  } = $props();
</script>

<label class="block">
  <div class="mb-1 flex items-center justify-between text-xs">
    <span class="flex items-center font-medium">
      {title}
      <GraphOptionsResetDot dirty={dirty} onReset={onReset} />
    </span>
    <span class="tabular-nums text-muted-foreground">{valueText}</span>
  </div>
  <input
    type="range"
    {min}
    {max}
    {step}
    {value}
    oninput={(e) => onInput(e.currentTarget.valueAsNumber)}
    class="h-1.5 w-full cursor-pointer accent-primary"
    aria-label={ariaLabel}
  />
  <div class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
    <span>{leftLabel}</span><span>{rightLabel}</span>
  </div>
</label>
