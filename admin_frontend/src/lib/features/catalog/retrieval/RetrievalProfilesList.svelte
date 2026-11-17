<script lang="ts">
  /**
   * Catalog → Profiles → Embedding profiles / Reranker profiles. Laid out like the voice profiles list: name and what
   * uses it, model and where it runs, details, actions. The same filter pills (All, Hiro, each extension, Unused).
   * A profile a locked use picked (its data is indexed with the model) can't be deleted.
   */
  import { Copy, Lock, Pencil, Plus, Trash2 } from '@lucide/svelte';
  import Panel from '$kit/ui/panel.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import Segmented from '$kit/ui/segmented.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import Loading from '$kit/ui/loading.svelte';
  import { Action } from '$kit/state/action.svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import RetrievalProfileEditorDialog from './RetrievalProfileEditorDialog.svelte';
  import { HIRO, retrieval as ctrl, type RetrievalKind, type RetrievalProfile } from './retrieval-controller.svelte';

  let { kind }: { kind: RetrievalKind } = $props();

  const WORDS = {
    embedding: {
      title: 'Embedding profiles',
      description:
        'How text becomes vectors for search: the embedding model. A graph or collection is built with one model and keeps it. Uses point at a profile.',
      new: 'New embedding profile',
      empty: 'No embedding profiles yet. Make one for each embedding model a search should use.'
    },
    reranker: {
      title: 'Reranker profiles',
      description: 'How search results are put in order of relevance: the reranking model, and where a local one runs. Uses point at a profile.',
      new: 'New reranker profile',
      empty: 'No reranker profiles yet. Make one for each reranking model a search should use.'
    }
  } as const;
  const w = $derived(WORDS[kind]);

  const GRID = 'minmax(200px,1.2fr) minmax(220px,1.3fr) minmax(200px,1.1fr) 300px';
  const title = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

  const all = $derived(ctrl.profiles(kind));
  const sourcesOf = (p: RetrievalProfile) => new Set(ctrl.usesOf(kind, p.id).map((u) => (u.source === HIRO ? HIRO : title(u.source))));
  const isUnused = (p: RetrievalProfile) => ctrl.usesOf(kind, p.id).length === 0;
  const sources = $derived(
    [...new Set(all.flatMap((p) => [...sourcesOf(p)]))].sort((a, b) => (a === HIRO ? -1 : b === HIRO ? 1 : a.localeCompare(b)))
  );
  const options = $derived([
    { value: 'all', label: 'All', count: all.length },
    ...sources.map((s) => ({ value: s, label: s, count: all.filter((p) => sourcesOf(p).has(s)).length })),
    { value: 'unused', label: 'Unused', count: all.filter(isUnused).length }
  ]);
  let source = $state('all');
  const rows = $derived(source === 'all' ? all : source === 'unused' ? all.filter(isUnused) : all.filter((p) => sourcesOf(p).has(source)));

  let confirmDelete = $state<string | null>(null);
  const deleting = new Action();
  async function remove(p: RetrievalProfile) {
    await deleting.run(() => ctrl.remove(kind, p.id));
    confirmDelete = null;
  }

  let editorOpen = $state(false);
  let editing = $state<RetrievalProfile | null>(null);
  let copyOf = $state<RetrievalProfile | null>(null);
  const edit = (p: RetrievalProfile | null) => {
    editing = p;
    copyOf = null;
    editorOpen = true;
  };
  const duplicate = (p: RetrievalProfile) => {
    editing = null;
    copyOf = p;
    editorOpen = true;
  };
</script>

<Panel title={w.title} description={w.description} class="grid gap-4">
  {#snippet actions()}
    <Segmented class="flex-wrap" label="Show profiles for" {options} value={source} onchange={(id) => (source = id)} />
    <Button onclick={() => edit(null)}><Plus size={15} /> {w.new}</Button>
  {/snippet}

  {#if ctrl.error}<Notice message={ctrl.error} />{/if}
  {#if deleting.error}<Notice message={deleting.error} />{/if}

  {#if ctrl.loading && !ctrl.prefs}
    <Loading label={`Reading ${w.title.toLowerCase()}…`} />
  {:else if !all.length}
    <EmptyState message={w.empty} />
  {:else}
    <TableShell layout="grid" minWidth={980} gridColumns={GRID}>
      {#snippet headRow()}
        <span>Name</span>
        <span>Model</span>
        <span>{kind === 'embedding' ? 'Vectors' : 'Runs'}</span>
        <span class="text-right">Actions</span>
      {/snippet}
      {#snippet body()}
        {#each rows as p (p.id)}
          {@const m = ctrl.model(kind, p.model)}
          {@const lock = ctrl.lockOf(kind, p.id)}
          <div class={TABLE_GRID_ROW} style:grid-template-columns={GRID}>
            <span class="grid content-start gap-1">
              <span class="flex items-center gap-2">
                <span class="font-sans text-sm font-semibold">{p.label}</span>
                {#if isUnused(p)}<Badge variant="outline">Unused</Badge>{/if}
              </span>
              {#if !isUnused(p)}<span class="text-xs text-muted-foreground">Used by {ctrl.usedByLine(kind, p.id)}</span>{/if}
            </span>
            <span class="grid min-w-0 content-start gap-1">
              <span class="flex min-w-0 items-center gap-2">
                <span class="min-w-0 truncate font-sans text-sm" title={m?.name ?? p.model}>{m?.name ?? p.model}</span>
                <Badge class="shrink-0" variant={m?.local ? 'secondary' : 'outline'}>{m?.local ? 'Local' : 'API'}</Badge>
              </span>
              {#if m}
                <span class="truncate text-xs text-muted-foreground">{m.provider}</span>
              {:else if ctrl.catalog.loaded}
                <span class="text-xs text-warning">Not in the catalog any more</span>
              {/if}
            </span>
            <span class="grid content-start gap-1">
              {#if kind === 'embedding'}
                <span class="text-sm">{m?.dims ? `${m.dims} dimensions` : m?.local ? 'Local model' : 'Made by the provider'}</span>
                {#if lock}
                  <span class="flex items-center gap-1 text-xs text-muted-foreground" title={lock}><Lock size={12} /> Data is indexed with it</span>
                {/if}
              {:else}
                <span class="text-sm">{m?.local ? `On ${p.device ? p.device.toUpperCase() : 'the best device found'}` : 'At the provider'}</span>
              {/if}
            </span>
            <span class="grid justify-items-end gap-1.5">
              <span class="flex flex-wrap justify-end gap-2">
                <Button size="sm" variant="outline" onclick={() => edit(p)}><Pencil size={13} /> Edit</Button>
                <Button size="sm" variant="outline" onclick={() => duplicate(p)}><Copy size={13} /> Duplicate</Button>
                <Button size="sm" variant="destructive" disabled={!!lock} title={lock} onclick={() => (confirmDelete = p.id)}
                  ><Trash2 size={13} /> Delete</Button
                >
              </span>
              {#if confirmDelete === p.id}
                <span class="flex flex-wrap items-center justify-end gap-2 text-xs">
                  Delete "{p.label}"?{ctrl.usesOf(kind, p.id).length ? ' Its uses will have no profile.' : ''}
                  <Button size="sm" variant="destructive" disabled={deleting.busy} onclick={() => remove(p)}>Delete</Button>
                  <Button size="sm" variant="ghost" onclick={() => (confirmDelete = null)}>Cancel</Button>
                </span>
              {/if}
            </span>
          </div>
        {/each}
      {/snippet}
    </TableShell>
  {/if}
</Panel>

<RetrievalProfileEditorDialog bind:open={editorOpen} {kind} profile={editing} {copyOf} />
