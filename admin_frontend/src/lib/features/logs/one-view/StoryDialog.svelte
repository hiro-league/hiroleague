<script lang="ts">
  // One story over the page (Logging and tracing plan, phase 6b), read from the core's log tools
  // (`/logs/stories/{id}`). Its head stays put: kind, name, title, when, how long, its problems and the parts it went
  // through. Under it, one tab at a time:
  //   Story    every kind drawn the same way: what started it (its first named line: the one part that differs by
  //            kind), what happened (its timed steps as a tree), and how it ended (its named step's end); its first
  //            problem on top when it had one. A conversation reads as a chat.
  //   Steps    its timed steps as bars
  //   Lines    its lines from every part, in order
  //   Records  what joins it by the same id: its graph run, its AI asks
  //
  // Built from: shadcn-svelte's Dialog, Tabs (line), Badge, Button and Table (in the kit's TableShell); the kit's
  // Loading, Notice and EmptyState; the Logs tab's level icon and colours. New: the start blocks, the steps' tree and
  // bars (StorySteps), the parts' path.
  import { base } from '$app/paths';
  import { ArrowRight, CircleCheck, CircleMinus, CircleX, Copy, List, TriangleAlert, User, Workflow } from '@lucide/svelte';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import * as Tabs from '$kit/components/ui/tabs/index.js';
  import * as Table from '$kit/components/ui/table/index.js';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import TableShell from '$kit/ui/table-shell.svelte';
  import Loading from '$kit/ui/loading.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import type { Notify } from '$kit/ui/toast.svelte';
  import { errorMessage } from '$kit/api/client';
  import { dateTime } from '$kit/format/time';
  import { cn } from '$lib/utils';
  import { getLogStory, type BriefLogLine, type LogStory, type StoryStepLine } from '$lib/api/logs';
  import { getGraphRun, getGraphRunsByStory, type GraphRunInspectResponse } from '$lib/api/graph-runs';
  import LogLevelIcon from '../shared/LogLevelIcon.svelte';
  import { can } from '$kit/state/pages';
  import { who } from '$kit/state/who.svelte';
  import { logLevelAccentClass, logLevelTextClass } from '../shared/logs-classes';
  import KindIcon from './KindIcon.svelte';
  import PartIcon from './PartIcon.svelte';
  import StorySteps from './StorySteps.svelte';
  import { kindLabel, type StoryStep } from './kinds';
  import { isPageArea, partLabel } from './parts';
  import { duration } from './story-format';

  type Props = { storyId: string; onClose: () => void; notify: Notify };
  let { storyId, onClose, notify }: Props = $props();

  let story = $state<LogStory | null>(null);
  let runIds = $state<string[]>([]);
  // A conversation's graph run: its nodes are the thinking, its run row holds the reply (the ledger's output preview)
  let run = $state<GraphRunInspectResponse | null>(null);
  let loading = $state(true);
  let failure = $state<string | null>(null);
  let tab = $state('story');
  let openLine = $state<number | null>(null);
  const PROBLEM = new Set(['WARNING', 'ERROR', 'CRITICAL']);

  $effect(() => {
    const asked = storyId;
    tab = 'story';
    openLine = null;
    run = null;
    loading = true;
    failure = null;
    // Permissions phase 2: a story's graph run shows what Hiro recalled about people: only with Graph runs
    const runsFor = can(who.me, 'logs.runs') ? getGraphRunsByStory(asked).catch(() => ({ run_ids: [] as string[] })) : Promise.resolve({ run_ids: [] as string[] });
    Promise.all([getLogStory(asked), runsFor])
      .then(async ([s, runs]) => {
        if (asked !== storyId) return;
        story = s;
        runIds = runs.run_ids;
        const last = runs.run_ids.at(-1);
        run = last ? await getGraphRun(last).catch(() => null) : null;
      })
      .catch((e) => (failure = errorMessage(e)))
      .finally(() => (loading = false));
  });

  // ---- what the lines say

  type Tree = StoryStepLine & { children: Tree[] };
  const fieldsOf = (r: BriefLogLine) => r.fields ?? {};
  const t0 = $derived(story?.rows[0]?.timestamp ?? 0);
  const offset = (ts: number) => `+${duration(Math.max(0, (ts - t0) * 1000))}`;
  // Its first named line (where it started) and its named step's end (how it ended)
  const startLine = $derived(story?.rows.find((r) => fieldsOf(r)['story.kind'] && !fieldsOf(r).step) ?? null);
  const endLine = $derived(story?.rows.find((r) => fieldsOf(r)['story.kind'] && fieldsOf(r).step) ?? null);
  const causeIndex = $derived(story ? story.rows.findIndex((r) => PROBLEM.has(r.level)) : -1);
  const startFields = $derived(
    Object.entries(startLine ? fieldsOf(startLine) : {}).filter(([k]) => !k.startsWith('story.'))
  );
  const asks = $derived((story?.rows ?? []).filter((r) => fieldsOf(r).step === 'ai.ask' || (fieldsOf(r).model && fieldsOf(r).cost)));

  const runNodes = $derived((run?.rows ?? []).filter((r) => r.row_kind === 'node'));
  const reply = $derived(run?.aggregate?.output_preview ?? '');
  const logsHref = $derived(`${base}/logs?tab=logs&msg_id=${encodeURIComponent(storyId)}`); // the Logs tab, this story's lines

  const tree = $derived.by<Tree[]>(() => {
    const steps = story?.steps ?? [];
    const byId = new Map<string, Tree>(steps.map((s) => [s.step_id, { ...s, children: [] }]));
    const roots: Tree[] = [];
    for (const node of byId.values()) {
      const parent = node.parent_step ? byId.get(node.parent_step) : undefined;
      (parent ? parent.children : roots).push(node);
    }
    const startOf = (n: Tree) => n.timestamp * 1000 - n.elapsed_ms;
    const order = (ns: Tree[]) => ns.sort((a, b) => startOf(a) - startOf(b)).forEach((n) => order(n.children));
    order(roots);
    return roots;
  });

  const bars = $derived.by<StoryStep[]>(() => {
    const out: StoryStep[] = [];
    const walk = (ns: Tree[], depth: number) => {
      for (const n of ns) {
        out.push({ step: n.step, source: n.source, outcome: n.outcome, elapsed_ms: n.elapsed_ms, depth,
                   start_ms: Math.max(0, n.timestamp * 1000 - n.elapsed_ms - t0 * 1000) });
        walk(n.children, depth + 1);
      }
    };
    walk(tree, 0);
    return out;
  });
  const total = $derived(Math.max(story?.took_ms ?? 0, ...bars.map((b) => b.start_ms + b.elapsed_ms), 1));

  async function copyId(id: string) {
    try {
      await navigator.clipboard.writeText(id);
      notify('success', 'Story id copied.');
    } catch {
      notify('error', "The story id couldn't be copied.");
    }
  }
</script>

{#snippet outcomeIcon(o: string)}
  {#if o === 'ok'}<CircleCheck size={14} class="shrink-0 text-success" />
  {:else if o === 'error'}<CircleX size={14} class="shrink-0 text-destructive" />
  {:else}<CircleMinus size={14} class="shrink-0 text-muted-foreground" />{/if}
{/snippet}

{#snippet steps(list: Tree[], depth: number)}
  <ul class={cn('space-y-1.5', depth > 0 && 'mt-1.5 border-l pl-4')}>
    {#each list as n (n.step_id)}
      <li>
        <div class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.82rem]">
          {@render outcomeIcon(n.outcome)}
          <span class={cn('font-mono text-xs', n.outcome === 'error' ? 'text-destructive' : 'text-foreground')}>{n.step}</span>
          <span class="inline-flex items-center gap-1 text-xs text-muted-foreground"><PartIcon source={n.source} size={11} />{partLabel(n.source)}</span>
          <span class="text-xs tabular-nums text-muted-foreground">· {duration(n.elapsed_ms)}</span>
        </div>
        {#if n.children.length}{@render steps(n.children, depth + 1)}{/if}
      </li>
    {/each}
  </ul>
{/snippet}

{#snippet label(text: string)}
  <p class="mb-1.5 text-[0.68rem] font-bold uppercase tracking-wide text-muted-foreground">{text}</p>
{/snippet}

<Dialog.Root open={!!storyId} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="flex h-[85vh] flex-col gap-3 sm:max-w-4xl">
    {#if loading && !story}
      <Dialog.Header><Dialog.Title>Story</Dialog.Title></Dialog.Header>
      <div class="grid flex-1 place-items-center"><Loading label="Reading the story…" /></div>
    {:else if failure}
      <Dialog.Header><Dialog.Title>Story</Dialog.Title></Dialog.Header>
      <Notice message={failure} class="px-3 py-2 text-sm" />
    {:else if !story || story.rows.length === 0}
      <Dialog.Header>
        <Dialog.Title>Story</Dialog.Title>
        <Dialog.Description class="font-mono text-xs">{storyId}</Dialog.Description>
      </Dialog.Header>
      <EmptyState message="No lines for this story" hint="Its lines may be older than the logs kept, or it never wrote one at info or above." />
    {:else}
      {@const s = story}
      <!-- The head stays put while the tabs below change -->
      <Dialog.Header class="space-y-1.5 pr-8">
        <div class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {#if s.kind}
            <Badge variant="secondary" class="gap-1"><KindIcon kind={s.kind} size={12} />{kindLabel(s.kind)}</Badge>
            {startLine ? partLabel(startLine.source) : ''} · {s.label}
          {:else}
            <Badge variant="outline" class="gap-1"><KindIcon kind="unknown" size={12} />Not named</Badge>
          {/if}
        </div>
        <Dialog.Title class="text-lg">{s.title || s.label || 'A story nobody named'}</Dialog.Title>
        <Dialog.Description class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span>{s.started}</span>
          <span>took {duration(s.took_ms)}</span>
          <span class={s.problems ? 'text-warning' : ''}>{s.problems ? `${s.problems} problem${s.problems === 1 ? '' : 's'}` : 'no problems'}</span>
          <span class="inline-flex flex-wrap items-center gap-1" aria-label="The parts it went through, in order">
            {#each s.sources as src, i (src)}
              {#if i > 0}<ArrowRight size={11} />{/if}<span class="inline-flex items-center gap-1"><PartIcon source={src} size={11} />{partLabel(src)}</span>
            {/each}
          </span>
          <a class="ml-auto inline-flex items-center gap-1 hover:text-foreground" href={logsHref} title="The Logs tab, filtered to this story's lines"><List size={12} />See its lines in Logs</a>
          <button type="button" class="inline-flex items-center gap-1 font-mono hover:text-foreground" title="Copy the story id" onclick={() => void copyId(s.story_id)}>{s.story_id.slice(0, 8)}<Copy size={11} /></button>
        </Dialog.Description>
      </Dialog.Header>

      <Tabs.Root bind:value={tab} class="flex min-h-0 flex-1 flex-col">
        <Tabs.List variant="line" class="w-full justify-start border-b">
          <Tabs.Trigger value="story" class="flex-none">Story</Tabs.Trigger>
          <Tabs.Trigger value="steps" class="flex-none" disabled={!s.steps.length}>Steps <span class="text-muted-foreground">{s.steps.length}</span></Tabs.Trigger>
          <Tabs.Trigger value="lines" class="flex-none">Lines <span class="text-muted-foreground">{s.rows.length}</span></Tabs.Trigger>
          <Tabs.Trigger value="records" class="flex-none" disabled={!runIds.length && !asks.length}>Records <span class="text-muted-foreground">{runIds.length + asks.length}</span></Tabs.Trigger>
        </Tabs.List>

        <!-- Story: every kind the same three parts; only "Started by" differs -->
        <Tabs.Content value="story" class="min-h-0 flex-1 overflow-y-auto pt-3">
          <div class="space-y-5">
            {#if causeIndex >= 0}
              {@const cause = s.rows[causeIndex]}
              <button
                type="button"
                class="flex w-full items-start gap-2 rounded-md bg-destructive/10 px-3 py-2 text-left text-[0.82rem] hover:bg-destructive/15"
                title="Show the line"
                onclick={() => { tab = 'lines'; openLine = causeIndex; }}
              >
                <TriangleAlert size={15} class="mt-0.5 shrink-0 text-destructive" />
                <span>
                  <span class="font-medium">First went wrong in {partLabel(cause.source)}:</span>
                  <span class={logLevelTextClass(cause.level)}>{cause.message}</span>
                  <span class="text-xs text-muted-foreground"> · {offset(cause.timestamp)}</span>
                </span>
              </button>
            {/if}

            {#if s.kind === 'conversation' && startLine}
              <!-- A conversation reads as a chat: the message, the thinking, the answer -->
              <div class="flex items-start gap-2">
                <User size={16} class="mt-1 shrink-0 text-muted-foreground" />
                <div class="max-w-[75%] rounded-lg bg-muted px-3 py-2 text-[0.82rem]">{s.title}</div>
              </div>
              <div class="ml-6 rounded-md border border-dashed px-3 py-2">
                {#if runNodes.length}
                  <p class="mb-1.5 text-xs text-muted-foreground">What it thought (its graph run)</p>
                  <ul class="space-y-1.5">
                    {#each runNodes as n, i (i)}
                      <li class="text-[0.82rem]">
                        <div class="flex flex-wrap items-center gap-x-2">
                          {@render outcomeIcon(n.status === 'error' || n.error_code ? 'error' : 'ok')}
                          <span class="font-mono text-xs">{n.node}</span>
                          {#if n.model}<span class="text-xs text-muted-foreground">· {n.model}</span>{/if}
                          {#if n.elapsed_ms}<span class="text-xs tabular-nums text-muted-foreground">· {duration(Number(n.elapsed_ms))}</span>{/if}
                          {#if Number(n.input_tokens) || Number(n.output_tokens)}<span class="text-xs tabular-nums text-muted-foreground">· {n.input_tokens} in / {n.output_tokens} out</span>{/if}
                        </div>
                        {#if n.output_preview}<p class="ml-6 text-xs text-muted-foreground">{n.output_preview}</p>{/if}
                      </li>
                    {/each}
                  </ul>
                {:else}
                  <p class="mb-1.5 text-xs text-muted-foreground">What it went through</p>
                  {#if tree.length}{@render steps(tree, 0)}{:else}<p class="text-xs text-muted-foreground">No timed steps.</p>{/if}
                  <p class="mt-2 text-xs text-muted-foreground">No graph run joins this story: the agent didn't run (no AI here, or it failed before).</p>
                {/if}
              </div>
              {#if reply}
                <div class="flex justify-end">
                  <div class="max-w-[75%] whitespace-pre-wrap rounded-lg bg-primary/10 px-3 py-2 text-[0.82rem]">{reply}</div>
                </div>
              {:else if endLine}
                <div class="flex justify-end">
                  <div class={cn('max-w-[75%] rounded-lg px-3 py-2 text-[0.82rem]', fieldsOf(endLine).outcome === 'error' ? 'bg-destructive/10' : 'bg-primary/10')}>
                    {fieldsOf(endLine).outcome === 'error' ? `It failed: ${fieldsOf(endLine).error ?? ''}` : `Answered after ${duration(Number(fieldsOf(endLine).elapsed_ms ?? 0))}`}
                    {#if runIds.length}<span class="text-xs text-muted-foreground"> · the reply is in its graph run</span>{/if}
                  </div>
                </div>
              {/if}
            {:else}
              <section>
                {@render label('Started by')}
                {#if startLine}
                  <p class="text-[0.82rem]"><span class="font-medium">{s.label}</span>: {s.title}</p>
                  {#if startFields.length}
                    <p class="mt-1 flex flex-wrap gap-x-3 font-mono text-[11px] text-muted-foreground">
                      {#each startFields as [k, v] (k)}<span>{k}={v}</span>{/each}
                    </p>
                  {/if}
                {:else}
                  <p class="text-[0.82rem] text-muted-foreground">Its first line: {s.rows[0].message}</p>
                {/if}
              </section>
              <section>
                {@render label('What happened')}
                {#if tree.length}{@render steps(tree, 0)}{:else}<p class="text-xs text-muted-foreground">No timed steps.</p>{/if}
              </section>
              <section>
                {@render label('How it ended')}
                {#if endLine}
                  {@const f = fieldsOf(endLine)}
                  <p class="flex items-center gap-2 text-[0.82rem]">
                    {@render outcomeIcon(f.outcome ?? '')}
                    <span class={f.outcome === 'error' ? 'text-destructive' : ''}>
                      {f.outcome === 'error' ? `Failed: ${f.error ?? ''}` : f.outcome === 'cancelled' ? 'Cancelled' : 'Done'}, after {duration(Number(f.elapsed_ms ?? 0))}
                    </span>
                  </p>
                {:else}
                  <p class="text-[0.82rem] text-muted-foreground">Still running, or its end isn't in the logs.</p>
                {/if}
              </section>
            {/if}
          </div>
        </Tabs.Content>

        <Tabs.Content value="steps" class="min-h-0 flex-1 overflow-y-auto pt-3">
          <StorySteps steps={bars} {total} />
        </Tabs.Content>

        <Tabs.Content value="lines" class="min-h-0 flex-1 overflow-y-auto pt-3">
          <TableShell>
            <Table.Header>
              <Table.Row>
                <Table.Head class="w-20">After</Table.Head>
                <Table.Head class="w-8"><span class="sr-only">Level</span></Table.Head>
                <Table.Head>Source</Table.Head>
                <Table.Head>Module</Table.Head>
                <Table.Head>Message</Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each s.rows as l, i (i)}
                {@const isOpen = openLine === i}
                <Table.Row
                  class={cn('cursor-pointer align-top text-xs', PROBLEM.has(l.level) && 'bg-warning/5', i === causeIndex && 'bg-destructive/10 hover:bg-destructive/15')}
                  onclick={() => (openLine = isOpen ? null : i)}
                >
                  <Table.Cell class="tabular-nums text-muted-foreground" title={dateTime(l.timestamp * 1000, { seconds: true })}>{offset(l.timestamp)}</Table.Cell>
                  <Table.Cell><LogLevelIcon level={l.level} size={14} class={logLevelAccentClass(l.level)} /></Table.Cell>
                  <Table.Cell class="whitespace-nowrap"><span class="inline-flex items-center gap-1.5"><PartIcon source={l.source} size={12} class="text-muted-foreground" />{partLabel(l.source)}</span></Table.Cell>
                  <Table.Cell class="whitespace-nowrap font-mono">{l.area}{#if isPageArea(l.area)} <span class="text-muted-foreground">(page)</span>{/if}</Table.Cell>
                  <Table.Cell class={logLevelTextClass(l.level)}>{l.message}</Table.Cell>
                </Table.Row>
                {#if isOpen && l.fields}
                  <Table.Row class="bg-muted/30 hover:bg-muted/30">
                    <Table.Cell></Table.Cell>
                    <Table.Cell colspan={4} class="py-2">
                      <dl class="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-0.5 text-xs">
                        {#each Object.entries(l.fields) as [k, val] (k)}
                          <dt class="font-mono text-muted-foreground">{k}</dt>
                          <dd class="whitespace-pre-wrap break-all font-mono">{val}</dd>
                        {/each}
                      </dl>
                    </Table.Cell>
                  </Table.Row>
                {/if}
              {/each}
            </Table.Body>
          </TableShell>
        </Tabs.Content>

        <Tabs.Content value="records" class="min-h-0 flex-1 overflow-y-auto pt-3">
          <ul class="divide-y rounded-md border">
            {#each runIds as id (id)}
              <li class="flex items-center gap-3 px-3 py-2 text-[0.82rem]">
                <Workflow size={14} class="shrink-0 text-muted-foreground" />
                <span class="min-w-0 flex-1">
                  <span class="font-medium">Graph run</span><span class="ml-2 font-mono text-xs text-muted-foreground">{id}</span>
                  {#if run?.aggregate && id === runIds.at(-1)}
                    <span class="ml-2 text-xs text-muted-foreground">{runNodes.length} nodes · {run.aggregate.cost_usd ? `$${run.aggregate.cost_usd}` : 'no cost'} · its memory and knowledge traces open there</span>
                  {/if}
                </span>
                <Button variant="outline" size="sm" class="h-7" href={`${base}/logs?tab=runs&story=${encodeURIComponent(s.story_id)}`}>Open</Button>
              </li>
            {/each}
            {#each asks as a, i (i)}
              <li class="flex items-center gap-3 px-3 py-2 text-[0.82rem]">
                <span class="min-w-0 flex-1">
                  <span class="font-medium">AI ask</span>
                  <span class="ml-2 text-xs text-muted-foreground">
                    {[fieldsOf(a).use, fieldsOf(a).model, fieldsOf(a).cost, fieldsOf(a).outcome].filter(Boolean).join(' · ') || a.message}
                  </span>
                </span>
                <span class="text-xs text-muted-foreground">{partLabel(a.source)} · {offset(a.timestamp)}</span>
              </li>
            {/each}
          </ul>
        </Tabs.Content>
      </Tabs.Root>
    {/if}
  </Dialog.Content>
</Dialog.Root>
