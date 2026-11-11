<script lang="ts">
  /**
   * Two-knob (range) slider for the Graph options "Filters" section — used for the Valid-date
   * and Creation-date edge filters. The kit Slider (type="multiple"). Controlled:
   * the parent owns [lo, hi] and gets `onChange` on every drag. `format` renders the value labels
   * (dates here). Graph-local on purpose; not a shared control.
   */
  import { Slider } from '$kit/components/ui/slider/index.js';

  let {
    min,
    max,
    step,
    value,
    format,
    onChange
  }: {
    min: number;
    max: number;
    step: number;
    /** Current [lo, hi]. */
    value: [number, number];
    /** Render a value as a label (e.g. a date string). */
    format: (v: number) => string;
    onChange: (lo: number, hi: number) => void;
  } = $props();
</script>

<div>
  <Slider
    type="multiple"
    {value}
    {min}
    {max}
    {step}
    onValueChange={(v: number[]) => onChange(v[0], v[1])}
    class="h-4"
  />
  <div class="mt-1 flex justify-between text-[10px] tabular-nums text-muted-foreground">
    <span>{format(value[0])}</span><span>{format(value[1])}</span>
  </div>
</div>
