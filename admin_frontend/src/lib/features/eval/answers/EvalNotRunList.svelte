<!--
  Not-run questions — the full bank's still-unanswered questions, as a selectable list below the
  answered table (the old Questions tab's job). Lets a fresh corpus (zero answers) still be fully
  selectable for a run. Collapsible; renders nothing when every question already has a row.
-->
<script lang="ts">
  import { ChevronDown, ChevronRight } from '@lucide/svelte';
  import { difficultyMeta } from '$lib/features/eval/shared/eval-display';
  import type { EvalQuestionItem } from '$lib/api/knowledge';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';

  interface Props {
    eval_: EvalModel;
    /** Bank questions with no answered row yet (already filter-narrowed by the pane). */
    questions: EvalQuestionItem[];
    /** 1-based bank position per question id — the stable "#" shown for a not-run row. */
    bankPos: Map<string, number>;
  }
  let { eval_, questions, bankPos }: Props = $props();

  let collapsed = $state(false);
</script>

{#if questions.length > 0}
  <div class="mt-4">
    <button
      type="button"
      class="flex items-center gap-1.5 font-sans"
      onclick={() => (collapsed = !collapsed)}
      aria-expanded={!collapsed}
    >
      {#if collapsed}
        <ChevronRight size={15} aria-hidden="true" />
      {:else}
        <ChevronDown size={15} aria-hidden="true" />
      {/if}
      <span class="text-sm font-semibold"
        >Not run <span class="font-normal text-muted-foreground">({questions.length})</span></span
      >
    </button>
    {#if !collapsed}
      <div class="mt-1 rounded-md border">
        <table class="w-full border-collapse font-sans text-sm">
          <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th class="px-2 py-1.5 text-center" title="Select questions to run">Run?</th>
              <th class="px-2 py-1.5 text-left">#</th>
              <th class="px-2 py-1.5 text-left">Question</th>
              <th class="px-2 py-1.5 text-left">Type</th>
              <th class="px-2 py-1.5 text-left">Difficulty</th>
            </tr>
          </thead>
          <tbody>
            {#each questions as q (q.id)}
              <tr class="border-t align-top {eval_.isSelected(q.id) ? 'bg-primary/5' : ''}">
                <td class="px-2 py-1.5 text-center">
                  <input
                    type="checkbox"
                    class="size-3.5"
                    checked={eval_.isSelected(q.id)}
                    onchange={() => eval_.toggleQuestion(q.id)}
                    title="Select for run"
                    aria-label="Select question for run"
                  />
                </td>
                <td class="px-2 py-1.5 font-mono tabular-nums text-xs text-muted-foreground"
                  >{bankPos.get(q.id) ?? ''}</td
                >
                <td class="px-2 py-1.5">
                  <span class="line-clamp-2" title={q.question}>{q.question}</span>
                  {#if q.subcategory}<span class="ml-1 text-[10px] text-muted-foreground"
                      >{q.subcategory}</span
                    >{/if}
                </td>
                <td class="px-2 py-1.5 text-xs text-muted-foreground">{q.category || '—'}</td>
                <td class="px-2 py-1.5">
                  {#if difficultyMeta(q.difficulty ?? '')}
                    {@const dm = difficultyMeta(q.difficulty ?? '')}
                    <span
                      class="inline-block rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide {dm?.cls}"
                      >{dm?.label}</span
                    >
                  {:else}
                    <span class="text-xs text-muted-foreground">—</span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
{/if}
