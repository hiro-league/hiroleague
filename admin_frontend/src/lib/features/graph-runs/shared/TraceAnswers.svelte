<script lang="ts">
  import HighlightText from './HighlightText.svelte';

  // The retrieval dialog's Question → Answer → Ideal header. The question is always present;
  // Answer/Ideal only appear in eval context. Each line highlights the active search query.
  let {
    question,
    llmAnswer = '',
    idealAnswer = '',
    query
  }: { question: string; llmAnswer?: string; idealAnswer?: string; query: string } = $props();
</script>

<div class="trace-answers">
  <div class="trace-answer">
    <span class="trace-answer__label trace-answer__label--q">Question</span>
    <span class="trace-answer__text"><HighlightText text={question} {query} /></span>
  </div>
  {#if llmAnswer}
    <div class="trace-answer">
      <span class="trace-answer__label trace-answer__label--llm">Answer</span>
      <span class="trace-answer__text"><HighlightText text={llmAnswer} {query} /></span>
    </div>
  {/if}
  {#if idealAnswer}
    <div class="trace-answer">
      <span class="trace-answer__label trace-answer__label--ideal">Ideal</span>
      <span class="trace-answer__text"><HighlightText text={idealAnswer} {query} /></span>
    </div>
  {/if}
</div>

<style>
  /* Question → Answer → Ideal. Question is always present; Answer/Ideal only in eval context. */
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

  .trace-answer__label--llm {
    color: var(--primary);
  }

  .trace-answer__label--ideal {
    color: #16a34a;
  }

  .trace-answer__text {
    color: var(--foreground);
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
