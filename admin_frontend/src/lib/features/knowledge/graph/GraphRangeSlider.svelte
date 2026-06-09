<script lang="ts">
  /**
   * Two-knob (range) slider for the Graph options "Filters" section — used for the Valid-date
   * and Creation-date edge filters. Built on the bits-ui Slider (type="multiple"). Controlled:
   * the parent owns [lo, hi] and gets `onChange` on every drag. `format` renders the value labels
   * (dates here). Graph-local on purpose; not a shared control.
   */
  import { Slider } from 'bits-ui';

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
  <Slider.Root
    type="multiple"
    {value}
    {min}
    {max}
    {step}
    onValueChange={(v) => onChange(v[0], v[1])}
    class="relative flex h-4 w-full touch-none items-center select-none"
  >
    {#snippet children({ thumbItems })}
      <span class="relative h-1.5 w-full grow overflow-hidden rounded-full bg-muted">
        <Slider.Range class="absolute h-full bg-primary" />
      </span>
      {#each thumbItems as thumb (thumb.index)}
        <Slider.Thumb
          index={thumb.index}
          class="block size-3.5 rounded-full border border-primary bg-background shadow transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        />
      {/each}
    {/snippet}
  </Slider.Root>
  <div class="mt-1 flex justify-between text-[10px] tabular-nums text-muted-foreground">
    <span>{format(value[0])}</span><span>{format(value[1])}</span>
  </div>
</div>
