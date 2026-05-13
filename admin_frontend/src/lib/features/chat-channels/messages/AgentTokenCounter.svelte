<script lang="ts">
  import { untrack } from 'svelte';
  import { ArrowDown, ArrowUp, Clock3 } from '@lucide/svelte';
  import { formatTokenCount } from './agent-message-meta';

  type Props = {
    inputValue: number;
    outputValue: number;
    costLabel?: string;
    elapsedLabel?: string;
    tooltip?: string;
    className?: string;
    /** Separates estimated price from token counts (distinct hue on both bubbles). */
    costClassName?: string;
    animate?: boolean;
  };

  let {
    inputValue,
    outputValue,
    costLabel = '',
    elapsedLabel = '',
    tooltip = '',
    className = '',
    costClassName = '',
    animate = true
  }: Props = $props();

  let displayInput = $state(0);
  let displayOutput = $state(0);
  let targetInput = 0;
  let targetOutput = 0;

  $effect(() => {
    const nextIn = Math.max(0, Math.trunc(inputValue));
    const nextOut = Math.max(0, Math.trunc(outputValue));

    if (!animate) {
      targetInput = nextIn;
      targetOutput = nextOut;
      displayInput = nextIn;
      displayOutput = nextOut;
      return;
    }

    if (nextIn === targetInput && nextOut === targetOutput) return;
    targetInput = nextIn;
    targetOutput = nextOut;

    if (typeof window === 'undefined') {
      displayInput = nextIn;
      displayOutput = nextOut;
      return;
    }

    const fromIn = untrack(() => displayInput);
    const fromOut = untrack(() => displayOutput);
    const startedAt = performance.now();
    const durationMs = 420;
    let frame = 0;

    function step(now: number) {
      const progress = Math.min(1, (now - startedAt) / durationMs);
      const eased = 1 - Math.pow(1 - progress, 3);
      displayInput = Math.round(fromIn + (nextIn - fromIn) * eased);
      displayOutput = Math.round(fromOut + (nextOut - fromOut) * eased);
      if (progress < 1) frame = window.requestAnimationFrame(step);
    }

    frame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(frame);
  });
</script>

<span
  class={`inline-flex w-fit max-w-full flex-wrap items-center gap-x-1 gap-y-0.5 rounded-sm px-0.5 font-sans text-[10px] font-semibold leading-none tabular-nums ${className}`}
  title={tooltip}
  aria-label={`${displayInput} input tokens (incl. cached), ${displayOutput} output tokens${
    costLabel ? `, estimated cost ${costLabel}` : ''
  }${elapsedLabel ? `, completed in ${elapsedLabel}` : ''}`}
>
  <span class="inline-flex items-center gap-0.5">
    <ArrowUp size={10} class="shrink-0 opacity-90" aria-hidden="true" />
    <span> {formatTokenCount(displayInput)} t</span>
  </span>
  <span class="opacity-70" aria-hidden="true">&middot;</span>
  <span class="inline-flex items-center gap-0.5">
    <ArrowDown size={10} class="shrink-0 opacity-90" aria-hidden="true" />
    <span> {formatTokenCount(displayOutput)} t</span>
  </span>
  {#if costLabel}
    <span class="opacity-70" aria-hidden="true">&middot;</span>
    <span class={costClassName || 'opacity-95'}>{costLabel}</span>
  {/if}
  {#if elapsedLabel}
    <span class="opacity-70" aria-hidden="true">&middot;</span>
    <span class="inline-flex items-center gap-0.5 opacity-95">
      <Clock3 size={10} class="shrink-0 opacity-90" aria-hidden="true" />
      <span>{elapsedLabel}</span>
    </span>
  {/if}
</span>
