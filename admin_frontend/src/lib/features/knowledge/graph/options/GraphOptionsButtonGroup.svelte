<script lang="ts">
  import Segmented from '$kit/ui/segmented.svelte';
  import GraphOptionsResetDot from './GraphOptionsResetDot.svelte';

  let {
    title,
    dirty = false,
    onReset,
    modes,
    value,
    onChange,
    ariaLabel
  }: {
    title: string;
    dirty?: boolean;
    onReset: () => void;
    modes: { value: string; label: string; title: string }[];
    value: string;
    onChange: (v: string) => void;
    ariaLabel: string;
  } = $props();
</script>

<div>
  <div class="mb-1 flex items-center text-xs">
    <span class="flex items-center font-medium">
      {title}
      <GraphOptionsResetDot dirty={dirty} onReset={onReset} />
    </span>
  </div>
  <Segmented options={modes} {value} onchange={onChange} label={ariaLabel} stretch />
</div>
