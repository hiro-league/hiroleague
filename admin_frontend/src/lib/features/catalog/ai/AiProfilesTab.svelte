<script lang="ts">
  /**
   * AI profiles list: each recipe with its model, thinking, budget and today's use, and its fallback
   * chain. New / Edit / Duplicate / Delete go through the controller (preferences `ai.profiles`).
   */
  import { Copy, Pencil, Plus, Trash2 } from '@lucide/svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
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
  const deleting = $derived(ai.deletingId ? ai.profiles.find((p) => p.id === ai.deletingId) : undefined);
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
    <Button onclick={() => ai.newProfile()}><Plus size={15} /> New profile</Button>
  </div>

  {#if ai.profilesLoading && ai.profiles.length === 0}
    <InlineLoading label="Loading AI profiles…" />
  {:else if ai.profilesError}
    <InlineDestructiveAlert title="Could not load AI profiles" message={ai.profilesError} />
  {:else if ai.profiles.length === 0}
    <InlineEmptyState message="No AI profiles yet." hint="Make one with New profile." />
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
        {#each ai.profiles as profile (profile.id)}
          {@const found = ai.modelOf(profile)}
          <!-- The server's list says where the profile runs and whether it can answer now. -->
          {@const kind = profile.server?.kind ?? found.provider?.kind ?? 'api'}
          {@const notReady = profile.server?.notReady ?? found.provider?.notReady}
          {@const share = usageShare(profile, kind)}
          {@const chain = chainLabel(ai.profiles, fallbackChain(ai.profiles, profile.id))}
          <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID}>
            <span class="grid content-start gap-1">
              <span class="font-sans text-sm font-semibold">{profile.name}</span>
              {#if ai.usedBy(profile.id).length}
                <span class="text-xs text-muted-foreground">Used by {ai.usedBy(profile.id).join(', ')}</span>
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
              <Button size="sm" variant="destructive-outline" onclick={() => ai.askDelete(profile.id)}>
                <Trash2 size={13} /> Delete
              </Button>
            </span>
          </div>
        {/each}
      {/snippet}
    </AdminTableShell>
  {/if}
</SectionCard>

<AiProfileEditorDialog {ai} />

<Dialog.ConfirmDialog
  open={!!deleting}
  onOpenChange={(next) => {
    if (!next) ai.cancelDelete();
  }}
  title={`Delete ${deleting?.name ?? 'profile'}?`}
  message={deleting && ai.usedBy(deleting.id).length
    ? `Used by ${ai.usedBy(deleting.id).join(', ')}. Those uses are left without a profile and those fallbacks are cleared.`
    : 'Nothing uses it.'}
  confirmLabel={ai.deleting ? 'Deleting…' : 'Delete'}
  pending={ai.deleting}
  onConfirm={() => ai.confirmDelete()}
/>
