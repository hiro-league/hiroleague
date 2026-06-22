<!--
  Ideal/actual answer in the slim row fold: clamp to 2 lines with a more/less toggle only when
  the clamped text actually overflows (not a character-length guess).
-->
<script lang="ts">
  import { ChevronDown, ChevronUp } from '@lucide/svelte';
  import EvalHighlight from '$lib/features/eval/shared/EvalHighlight.svelte';

  interface Props {
    text: string;
    searchTerm: string;
    /** Parent bulk expand/collapse (expand-all toolbar buttons). */
    bulkTextOpen?: boolean;
    bulkTextTick?: number;
  }
  let { text, searchTerm, bulkTextOpen = false, bulkTextTick = 0 }: Props = $props();

  let open = $state(false);
  let clampEl = $state<HTMLElement | null>(null);
  let overflows = $state(false);

  function measureOverflow() {
    const el = clampEl;
    if (!el || open) return;
    overflows = el.scrollHeight > el.clientHeight + 1;
  }

  $effect(() => {
    text;
    searchTerm;
    open;
    const el = clampEl;
    if (!el) return;

    measureOverflow();
    const raf = requestAnimationFrame(measureOverflow);
    const ro = new ResizeObserver(measureOverflow);
    ro.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  });

  // Collapse-all: close every clamped answer on the bulk tick.
  $effect(() => {
    bulkTextTick;
    if (bulkTextTick === 0) return;
    if (!bulkTextOpen) open = false;
  });

  // Expand-all: open each answer that actually overflows once measured.
  $effect(() => {
    if (!bulkTextOpen || bulkTextTick === 0) return;
    overflows;
    if (overflows) open = true;
  });
</script>

<div class="min-w-0 flex-1">
  <div bind:this={clampEl} class="clamp" class:clamp--open={open}><EvalHighlight {text} term={searchTerm} /></div>
  {#if overflows || open}
    <button type="button" class="clamp-toggle" onclick={() => (open = !open)}>
      {#if open}<ChevronUp size={11} aria-hidden="true" />less{:else}<ChevronDown size={11} aria-hidden="true" />more{/if}
    </button>
  {/if}
</div>

<style>
  .clamp {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .clamp--open {
    display: block;
    -webkit-line-clamp: unset;
    line-clamp: unset;
    overflow: visible;
  }

  .clamp-toggle {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    margin-top: 2px;
    padding: 0;
    appearance: none;
    border: none;
    background: transparent;
    font-size: 10px;
    font-weight: 600;
    color: var(--primary);
    cursor: pointer;
  }

  .clamp-toggle:hover {
    text-decoration: underline;
  }
</style>
