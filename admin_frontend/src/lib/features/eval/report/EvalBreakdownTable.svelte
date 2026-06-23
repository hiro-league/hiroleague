<!--
  One collapsible report breakdown table: a bigger title with its OWN collapse toggle over a
  per-bucket × leg table. Two visual groups per leg — the ANSWER-TYPE distribution (colored
  Pass/Partial/Fail/Abstain icons) then the METRICS group (Recall Accuracy, Score x/y + %,
  Correct x/y + %, optional Evidence recall) — separated by a divider, with a colored Total row.
  ``header`` labels the first column; ``cols`` are the legs (memory = single ``recall``).
-->
<script lang="ts">
  import {
    ChevronDown,
    ChevronRight,
    CircleCheck,
    CircleDashed,
    CircleSlash,
    CircleX
  } from '@lucide/svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { fmtScore, pct } from '$lib/features/eval/shared/eval-format';
  import { legLabel } from '$lib/features/eval/shared/eval-display';
  import { breakdownTotals } from '$lib/features/eval/shared/eval-derive';
  import type { EvalCategoryStat } from '$lib/features/eval/shared/eval-events';
  import { ADMIN_TABLE_HEAD } from '$lib/styling/admin-tokens';

  interface Props {
    title: string;
    bc: Record<string, EvalCategoryStat>;
    cols: string[];
    header: string;
    /** Collapse state is owned by the parent (EvalReportPane) so it persists across re-mounts. */
    collapsed: boolean;
    onToggleCollapsed: () => void;
  }
  let { title, bc, cols, header, collapsed, onToggleCollapsed }: Props = $props();

  // Answer-mark groups: colored icon + name (mirrors the saved-badge icons).
  const MARK_GROUP_META = [
    { key: 'pass', name: 'Pass', Icon: CircleCheck, cls: 'text-emerald-600 dark:text-emerald-400' },
    { key: 'partial', name: 'Partial', Icon: CircleDashed, cls: 'text-amber-600 dark:text-amber-400' },
    { key: 'fail', name: 'Fail', Icon: CircleX, cls: 'text-rose-600 dark:text-rose-400' },
    { key: 'abstain', name: 'Abstain', Icon: CircleSlash, cls: 'text-muted-foreground' }
  ] as const;

  const multi = $derived(cols.length > 1);
  const totals = $derived(breakdownTotals(bc, cols));
  // Show the Evidence-recall column based on THIS table's own data (LoCoMo/BEAM gold evidence).
  const hasEv = $derived(Object.values(bc).some((b) => (b.evidence_total ?? 0) > 0));
</script>

{#snippet legHead()}
  {#each cols as mode (mode)}
    {#each MARK_GROUP_META as grp, gi (grp.key)}
      {@const Icon = grp.Icon}
      <th class="px-1.5 py-1 text-center {gi === 0 && multi ? 'border-l' : ''}">
        <span class="inline-flex items-center gap-1 {grp.cls}">
          <Icon size={12} aria-hidden="true" />{grp.name}
        </span>
      </th>
    {/each}
    <th class="border-l-2 border-border px-1.5 py-1 text-center" title="Recall Accuracy — the recalled facts/entities/episodes include the items required to answer correctly (of judged rows)">Recall&nbsp;Accuracy</th>
    <th class="px-1.5 py-1 text-center" title="Score — pass = 1 point, partial answer = ½ point, fail/abstain when an answer exists = 0 points">Score</th>
    <th class="px-1.5 py-1 text-center" title="Score % (of total)">Score&nbsp;%</th>
    <th class="px-1.5 py-1 text-center" title="Correct Answers — Pass = 1 point, anything else = 0 points (more restrictive than Score)">Correct&nbsp;Answers</th>
    <th class="px-1.5 py-1 text-center" title="Correct Answers % (of total)">Correct&nbsp;%</th>
    {#if hasEv}
      <th class="border-l-2 border-border px-1.5 py-1 text-center" title="Evidence recall — gold evidence episodes the recall covered (matched / total + %), summed across this bucket (LoCoMo / BEAM corpora)">Evidence&nbsp;recall</th>
    {/if}
  {/each}
{/snippet}

{#snippet bdCells(st: EvalCategoryStat, flatCorrect: number, isTotal = false)}
  {@const tone = isTotal ? 'text-foreground font-semibold' : 'text-muted-foreground'}
  {#each cols as mode (mode)}
    {@const g = st.groups?.[mode] ?? { pass: 0, partial: 0, fail: 0, abstain: 0 }}
    {@const judged = g.pass + g.partial + g.fail + g.abstain}
    {@const correct = st.correct?.[mode] ?? 0}
    {@const score = st.score?.[mode] ?? 0}
    {@const recallOk = st.recall_ok?.[mode] ?? 0}
    {@const win = mode !== 'flat' && correct > flatCorrect}
    {@const winCls = win ? 'font-semibold text-emerald-600' : isTotal ? 'text-foreground font-semibold' : 'text-foreground'}
    <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone} {multi ? 'border-l' : ''}">{g.pass}</td>
    <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{g.partial}</td>
    <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{g.fail}</td>
    <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{g.abstain}</td>
    <td class="border-l-2 border-border px-1.5 py-1.5 text-center font-mono tabular-nums {tone}" title="{recallOk}/{judged} judged">{pct(recallOk, judged)}</td>
    <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{fmtScore(score)}/{st.total}</td>
    <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{pct(score, st.total)}</td>
    <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {tone}">{correct}/{st.total}</td>
    <td class="px-1.5 py-1.5 text-center font-mono tabular-nums {winCls}">{pct(correct, st.total)}</td>
    {#if hasEv}
      {@const em = st.evidence_matched ?? 0}
      {@const et = st.evidence_total ?? 0}
      <td
        class="border-l-2 border-border px-1.5 py-1.5 text-center font-mono tabular-nums {tone}"
        title="{em}/{et} gold evidence episodes recalled across this {isTotal ? 'report' : 'bucket'}"
      >{#if et > 0}{em}/{et} · {pct(em, et)}{:else}—{/if}</td>
    {/if}
  {/each}
{/snippet}

<button
  type="button"
  class="mt-5 flex items-center gap-1.5 font-sans"
  onclick={onToggleCollapsed}
  aria-expanded={!collapsed}
>
  {#if collapsed}
    <ChevronRight size={15} aria-hidden="true" />
  {:else}
    <ChevronDown size={15} aria-hidden="true" />
  {/if}
  <span class="text-sm font-semibold">{title}</span>
</button>
{#if !collapsed}
  <div class="mt-2">
    <AdminTableShell>
      <thead class={ADMIN_TABLE_HEAD}>
        {#if multi}
          <tr>
            <th class="px-3 py-2 text-left" rowspan="2">{header}</th>
            <th class="px-3 py-2 text-center" rowspan="2">Total</th>
            {#each cols as mode (mode)}
              <th class="border-l px-3 py-1 text-center" colspan="9">{legLabel(mode)}</th>
            {/each}
          </tr>
          <tr>{@render legHead()}</tr>
        {:else}
          <tr>
            <th class="px-3 py-2 text-left">{header}</th>
            <th class="px-3 py-2 text-center">Total</th>
            {@render legHead()}
          </tr>
        {/if}
      </thead>
      <tbody>
        {#each Object.entries(bc) as [cat, st] (cat)}
          <tr class="border-t">
            <td class="px-3 py-1.5">{cat}</td>
            <td class="px-3 py-1.5 text-center font-mono tabular-nums text-muted-foreground">{st.total}</td>
            {@render bdCells(st, st.correct?.flat ?? 0)}
          </tr>
        {/each}
        <tr class="border-t-2 border-primary/40 bg-primary/10 font-semibold text-foreground">
          <td class="px-3 py-1.5">Total</td>
          <td class="px-3 py-1.5 text-center font-mono tabular-nums">{totals.total}</td>
          {@render bdCells(totals, totals.correct.flat ?? 0, true)}
        </tr>
      </tbody>
    </AdminTableShell>
  </div>
{/if}
