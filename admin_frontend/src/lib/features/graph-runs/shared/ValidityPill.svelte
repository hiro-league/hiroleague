<script lang="ts">
  // Bi-temporal validity marker shown before a fact: current (✓ green) vs superseded (✗ red).
  // Extracted from both trace dialogs, where the span + `.vpill` CSS were duplicated byte-for-byte.
  let { current, title = '' }: { current: boolean; title?: string } = $props();
</script>

<span class="vpill" class:vpill--ok={current} class:vpill--bad={!current} {title}>
  {current ? '✓' : '✗'}
</span>

<style>
  .vpill {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    line-height: 1;
    border: 1px solid transparent;
    /* Never inherit a struck row's line-through (retrieval "dropped" rows) — the pill stays legible. */
    text-decoration: none;
  }

  .vpill--ok {
    color: #16a34a;
    background: color-mix(in srgb, #16a34a 16%, transparent);
    border-color: color-mix(in srgb, #16a34a 45%, transparent);
  }

  .vpill--bad {
    color: #dc2626;
    background: color-mix(in srgb, #dc2626 16%, transparent);
    border-color: color-mix(in srgb, #dc2626 45%, transparent);
  }
</style>
