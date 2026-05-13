<script lang="ts">
  import { untrack } from 'svelte';
  import { formatTokenCount } from './agent-message-meta';

  type Props = {
    value: number;
    tooltip?: string;
    className?: string;
  };

  let { value, tooltip = '', className = '' }: Props = $props();
  let displayValue = $state(0);
  let currentTarget = 0;

  $effect(() => {
    const next = Math.max(0, Math.trunc(value));
    if (next === currentTarget) return;
    currentTarget = next;

    if (typeof window === 'undefined') {
      displayValue = next;
      return;
    }

    const from = untrack(() => displayValue);
    const startedAt = performance.now();
    const durationMs = 420;
    let frame = 0;

    function step(now: number) {
      const progress = Math.min(1, (now - startedAt) / durationMs);
      const eased = 1 - Math.pow(1 - progress, 3);
      displayValue = Math.round(from + (next - from) * eased);
      if (progress < 1) frame = window.requestAnimationFrame(step);
    }

    frame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(frame);
  });
</script>

<span
  class={`inline-flex w-fit items-center rounded-sm px-0.5 font-sans text-[10px] font-semibold leading-none tabular-nums ${className}`}
  title={tooltip}
  aria-label={`${displayValue} output tokens`}
>
  {formatTokenCount(displayValue)} tokens
</span>
