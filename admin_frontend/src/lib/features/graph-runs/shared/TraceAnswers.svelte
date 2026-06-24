<script lang="ts">
  import Highlight from '$lib/search/Highlight.svelte';

  // The retrieval dialog header question line. Gold / our answers live on the Overview tab.
  let { question, query }: { question: string; query: string } = $props();
</script>

<div class="trace-answers">
  <div class="trace-answer">
    <span class="trace-answer__label trace-answer__label--q">Question</span>
    <span class="trace-answer__text"><Highlight text={question} {query} /></span>
  </div>
</div>

<style>
  /* Question line under the dialog title row. */
  .trace-answers {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 6px;
  }

  .trace-answer {
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 12px;
  }

  .trace-answer__label {
    flex: none;
    width: 58px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted-foreground);
  }

  .trace-answer__label--q {
    color: var(--foreground);
  }

  .trace-answer__text {
    color: var(--foreground);
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
