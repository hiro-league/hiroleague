<script lang="ts">
  /**
   * Catalog → Profiles → Uses, the searching part of one source (Hiro, or an extension): its embedding uses and its
   * reranking uses, each pointed at a profile of that family. The same table as the AI and voice uses. Hiro's four are
   * its preference fields (they replaced the default embedder and reranker and their per-search models); an
   * extension's are the ones it declared. A locked embedder (its data is indexed) keeps its pick.
   */
  import { Lock } from '@lucide/svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import Notice from '$kit/ui/notice.svelte';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { cn } from '$lib/utils';
  import { retrieval as ctrl, type RetrievalKind, type RetrievalUse } from './retrieval-controller.svelte';

  let { source }: { source: string } = $props();

  const GRID = 'minmax(200px,1.1fr) minmax(170px,0.9fr) minmax(200px,1fr) minmax(240px,1.4fr)';
  const GROUPS: { kind: RetrievalKind; title: string; text: string; needs: string }[] = [
    {
      kind: 'embedding',
      title: 'Embedding',
      text: 'The embedding profile each search builds its vectors with. A graph or collection keeps the model it was built with.',
      needs: 'vectors'
    },
    { kind: 'reranker', title: 'Reranking', text: 'The reranker profile that puts search results in order. Not set: results keep their search order.', needs: 'an order' }
  ];

  let busy = $state<string | null>(null);
  let error = $state('');

  async function pick(use: RetrievalUse, value: string) {
    busy = use.key;
    error = (await ctrl.pick(use, value || null)) ?? '';
    busy = null;
  }

  function note(use: RetrievalUse): { text: string; warn: boolean } {
    if (use.removed) return { text: `No longer declared by ${use.source}.`, warn: false };
    const p = use.profileId ? ctrl.profiles(use.kind).find((x) => x.id === use.profileId) : undefined;
    if (!p) {
      if (use.profileId) return { text: `No profile "${use.profileId}": pick another.`, warn: true };
      return use.kind === 'embedding'
        ? { text: "No profile: this search can't index or search.", warn: true }
        : { text: 'No reranker: results keep their search order.', warn: false };
    }
    const m = ctrl.model(use.kind, p.model);
    const words = [m?.provider, m?.name ?? p.model].filter(Boolean).join(' · ');
    return { text: [words, use.lockedBecause ?? use.note].filter(Boolean).join('. '), warn: false };
  }
</script>

{#if error}<Notice message={error} />{/if}
{#each GROUPS as g (g.kind)}
  {@const rows = ctrl.uses.filter((u) => u.source === source && u.kind === g.kind)}
  {#if rows.length}
    <div class="mt-3">
      <h4 class="font-sans text-base font-semibold text-primary">
        {g.title} <span class="text-sm font-normal text-muted-foreground">· {rows.length} {rows.length === 1 ? 'use' : 'uses'}</span>
      </h4>
      <p class="text-xs text-muted-foreground">{g.text}</p>
    </div>
    <TableShell layout="grid" minWidth={900} gridColumns={GRID}>
      {#snippet headRow()}
        <span>Use</span>
        <span>Needs</span>
        <span>Profile</span>
        <span>Note</span>
      {/snippet}
      {#snippet body()}
        {#each rows as use (use.key)}
          {@const n = note(use)}
          {@const known = !use.profileId || ctrl.profiles(g.kind).some((p) => p.id === use.profileId)}
          <div class={cn(TABLE_GRID_ROW, use.removed && 'opacity-60')} style:grid-template-columns={GRID}>
            <span class="flex items-start gap-2">
              <span class="font-sans text-sm font-semibold">{use.label}</span>
              {#if use.lockedBecause}<Lock size={13} class="mt-0.5 text-muted-foreground" />{/if}
            </span>
            <span><Badge variant="secondary">{g.needs}</Badge></span>
            <span>
              <PickSelect
                class="h-9 w-full text-sm"
                label={`Profile for ${use.label}`}
                value={use.profileId ?? ''}
                disabled={!!use.lockedBecause || use.removed || busy === use.key}
                title={use.lockedBecause}
                options={[
                  { value: '', label: 'No profile' },
                  ...ctrl.profiles(g.kind).map((p) => ({ value: p.id, label: p.label })),
                  ...(!known && use.profileId ? [{ value: use.profileId, label: `${use.profileId} (missing)` }] : [])
                ]}
                onchange={(v) => void pick(use, v)}
              />
            </span>
            <span class={cn('text-sm', n.warn ? 'text-warning' : 'text-muted-foreground')}>{n.text}</span>
          </div>
        {/each}
      {/snippet}
    </TableShell>
  {/if}
{/each}
