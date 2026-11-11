<script lang="ts">
  /**
   * AI profiles list: each recipe with its model, thinking, budget and today's use, and its fallback
   * chain. New / Edit / Duplicate / Delete go through the controller (preferences `ai.profiles`).
   *
   * Phase 7b step 5: the default profiles of Hiro's jobs (`preset` set) are rows of the same table:
   * a "Default" badge, "Used by Hiro: <jobs>", and Restore default (confirmed first) instead of Delete.
   * The source filter shows one source at a time: Hiro (profiles its jobs use), each extension (the
   * profiles its uses ask with), Unused — a profile reached as a fallback counts for its source too.
   */
  import { Copy, Pencil, Plus, RotateCcw, Trash2 } from '@lucide/svelte';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import SourceFilter, { type SourceOption } from '$lib/components/page/SourceFilter.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import ConfirmDialog from '$lib/ui/ConfirmDialog.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import Loading from '$kit/ui/loading.svelte';
  import { ADMIN_SECTION_HEADING_LG } from '$lib/styling/admin-tokens';
  import AiProfileEditorDialog from './AiProfileEditorDialog.svelte';
  import type { AiController } from './ai-controller.svelte';
  import {
    budgetLabel,
    chainLabel,
    fallbackChain,
    PROVIDER_KIND_LABELS,
    thinkingWords,
    usageLabel,
    usageShare
  } from './ai-profile-rules';

  let { ai }: { ai: AiController } = $props();

  const GRID = 'minmax(180px,1.1fr) minmax(200px,1.3fr) 90px minmax(210px,1.2fr) minmax(180px,1fr) 330px';
  const KIND_BADGE = { api: 'outline', local: 'secondary', plan: 'default' } as const;
  // One source at a time: Hiro (its jobs), each extension (its uses), or the unused ones for cleanup.
  let source = $state('all');
  const HIRO = 'Hiro';
  /** Who asks with this profile — "Hiro" for its jobs, an extension for its uses — directly or as a
   *  fallback further down the chain. */
  function sourcesOf(id: string, seen = new Set<string>()): Set<string> {
    if (seen.has(id)) return new Set();
    seen.add(id);
    const out = new Set(ai.uses.filter((u) => u.profileId === id).map((u) => u.extension));
    if (ai.jobsUsing(id).length) out.add(HIRO);
    for (const p of ai.profiles) if (p.fallbackId === id) for (const s of sourcesOf(p.id, seen)) out.add(s);
    return out;
  }
  const extensions = $derived(ai.useGroups.map((g) => g.extension).filter((e) => e !== HIRO));
  const isUnused = (id: string) => !ai.usedBy(id).length && !ai.jobsUsing(id).length;
  const unused = $derived(ai.profiles.filter((p) => isUnused(p.id)));
  const sourceOptions = $derived<SourceOption[]>([
    { id: 'all', label: 'All', count: ai.profiles.length },
    { id: HIRO, label: 'Hiro', count: ai.profiles.filter((p) => sourcesOf(p.id).has(HIRO)).length },
    ...extensions.map((e) => ({ id: e, label: e, count: ai.profiles.filter((p) => sourcesOf(p.id).has(e)).length })),
    { id: 'unused', label: 'Unused', count: unused.length }
  ]);
  const shownProfiles = $derived(
    source === 'all' ? ai.profiles : source === 'unused' ? unused : ai.profiles.filter((p) => sourcesOf(p.id).has(source))
  );
  const deleting = $derived(ai.deletingId ? ai.profiles.find((p) => p.id === ai.deletingId) : undefined);
  const restoringProfile = $derived(ai.restoringId ? ai.profiles.find((p) => p.id === ai.restoringId) : undefined);
  const deleteMessage = $derived.by(() => {
    if (!deleting) return '';
    const used = ai.usedBy(deleting.id);
    const jobs = ai.jobsUsing(deleting.id);
    const parts: string[] = [];
    if (used.length) parts.push(`Used by ${used.join(', ')}. Those uses are left without a profile and those fallbacks are cleared.`);
    if (jobs.length) parts.push(`Hiro's ${jobs.join(', ')} will borrow the profile of the job they fall back to.`);
    return parts.join(' ') || 'Nothing uses it.';
  });
</script>

<SectionCard class="grid gap-4">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class={ADMIN_SECTION_HEADING_LG}>AI profiles</h3>
      <p class="font-sans text-sm text-muted-foreground">
        A profile is one recipe for asking: the model, how hard it thinks, what it may spend, and who
        asks instead when it can't answer. Uses point at a profile.
      </p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <!-- Hiro's profiles, each extension's, or the unused ones — never all mixed unless asked. -->
      <SourceFilter options={sourceOptions} value={source} onchange={(id) => (source = id)} />
      <Button onclick={() => ai.newProfile()}><Plus size={15} /> New profile</Button>
    </div>
  </div>

  {#if ai.profilesLoading && ai.profiles.length === 0}
    <Loading label="Loading AI profiles…" />
  {:else if ai.profilesError}
    <Notice title="Could not load AI profiles" message={ai.profilesError} />
  {:else if ai.profiles.length === 0}
    <EmptyState message="No AI profiles yet." hint="Make one with New profile." />
  {:else}
    <AdminTableShell layout="grid" minWidth={1260} gridColumns={GRID}>
      {#snippet headRow()}
        <span>Name</span>
        <span>Model</span>
        <span>Thinking</span>
        <span>Budget and today</span>
        <span>Fallback</span>
        <span class="text-right">Actions</span>
      {/snippet}
      {#snippet body()}
        {#each shownProfiles as profile (profile.id)}
          {@const found = ai.modelOf(profile)}
          <!-- The server's list says where the profile runs and whether it can answer now. -->
          {@const kind = profile.server?.kind ?? found.provider?.kind ?? 'api'}
          {@const notReady = profile.server?.notReady ?? found.provider?.notReady}
          {@const share = usageShare(profile, kind)}
          {@const chain = chainLabel(ai.profiles, fallbackChain(ai.profiles, profile.id))}
          {@const used = ai.usedBy(profile.id)}
          {@const hiroJobs = ai.jobsUsing(profile.id)}
          <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID}>
            <span class="grid content-start gap-1">
              <span class="flex flex-wrap items-center gap-1.5">
                <span class="font-sans text-sm font-semibold">{profile.name}</span>
                {#if profile.preset}
                  <Badge variant="outline">Default</Badge>
                  <FieldHelp
                    text={`Hiro's default profile for ${ai.jobLabel(profile.preset) || profile.preset}. Edit it freely; Restore default brings back the job's first settings (thinking, temperature, max tokens). It can't be deleted.`}
                  />
                {/if}
                {#if !used.length && !hiroJobs.length}<Badge variant="outline">Unused</Badge>{/if}
              </span>
              {#if hiroJobs.length}
                <span class="text-xs text-muted-foreground">Used by Hiro: {hiroJobs.join(', ')}</span>
              {/if}
              {#if used.length}
                <span class="text-xs text-muted-foreground">Used by {used.join(', ')}</span>
              {/if}
            </span>
            <span class="grid content-start gap-1">
              <span class="flex items-center gap-2">
                <span class="truncate font-sans text-sm">{found.model?.name ?? profile.model}</span>
                <Badge variant={KIND_BADGE[kind]}>{PROVIDER_KIND_LABELS[kind]}</Badge>
              </span>
              <span class="truncate text-xs text-muted-foreground">{profile.server?.providerLabel || found.provider?.label || 'Unknown provider'}</span>
              {#if notReady}
                <span class="text-xs text-amber-700 dark:text-amber-300">{notReady}</span>
              {/if}
            </span>
            <span class="text-sm">{thinkingWords(profile.thinking)}</span>
            <span class="grid content-start gap-1">
              <span class="text-sm">{budgetLabel(profile, kind)}</span>
              <span class="text-xs text-muted-foreground">{usageLabel(profile, kind)}</span>
              {#if share !== null}
                <span class="h-1.5 w-full max-w-48 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                  <span
                    class="block h-full rounded-full {share >= 0.9 ? 'bg-destructive' : share >= 0.6 ? 'bg-amber-500' : 'bg-primary'}"
                    style:width="{Math.round(share * 100)}%"
                  ></span>
                </span>
              {/if}
            </span>
            <span class="text-sm text-muted-foreground">{chain || 'None'}</span>
            <span class="flex flex-wrap justify-end gap-2">
              <Button size="sm" variant="outline" onclick={() => ai.editProfile(profile.id)}>
                <Pencil size={13} /> Edit
              </Button>
              <Button size="sm" variant="outline" onclick={() => ai.duplicateProfile(profile.id)}>
                <Copy size={13} /> Duplicate
              </Button>
              {#if profile.preset}
                <!-- A job's default profile: never deleted; Restore default puts its job's tuning back. -->
                <Button
                  size="sm"
                  variant="outline"
                  title="Back to the settings it started with"
                  onclick={() => ai.askRestore(profile.id)}
                >
                  <RotateCcw size={13} /> Restore default
                </Button>
              {:else}
                <Button size="sm" variant="destructive" onclick={() => ai.askDelete(profile.id)}>
                  <Trash2 size={13} /> Delete
                </Button>
              {/if}
            </span>
          </div>
        {/each}
      {/snippet}
    </AdminTableShell>
  {/if}
</SectionCard>

<AiProfileEditorDialog {ai} />

<ConfirmDialog
  open={!!deleting}
  onOpenChange={(next) => {
    if (!next) ai.cancelDelete();
  }}
  title={`Delete ${deleting?.name ?? 'profile'}?`}
  message={deleteMessage}
  confirmLabel={ai.deleting ? 'Deleting…' : 'Delete'}
  pending={ai.deleting}
  onConfirm={() => ai.confirmDelete()}
/>

<ConfirmDialog
  open={!!restoringProfile}
  onOpenChange={(next) => {
    if (!next) ai.cancelRestore();
  }}
  title={`Restore ${restoringProfile?.name ?? 'profile'}?`}
  message={`Its thinking, temperature and max tokens go back to ${ai.jobLabel(restoringProfile?.preset ?? null) || 'its job'}'s defaults, and its context window and extra instructions are cleared. Its model, name, limits and fallback stay.`}
  confirmLabel={ai.restoring ? 'Restoring…' : 'Restore default'}
  destructive={false}
  pending={ai.restoring}
  onConfirm={() => ai.confirmRestore()}
/>
