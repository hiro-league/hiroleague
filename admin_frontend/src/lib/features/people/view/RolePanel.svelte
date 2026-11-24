<script lang="ts">
  /**
   * One role on People → Roles: its name and what it is for, who holds it, and its rights in each app the filter
   * shows. A right is ticked, or, for a right about people's things, granted for their own or for everyone's
   * (Permissions phase 1). Every change saves at once and the app follows.
   */
  import { Lock, Trash2, UserRound } from '@lucide/svelte';
  import DetailPanel from '$kit/ui/detail-panel.svelte';
  import SectionLabel from '$kit/ui/section-label.svelte';
  import Segmented from '$kit/ui/segmented.svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import { Checkbox } from '$kit/components/ui/checkbox/index.js';
  import { Input } from '$kit/components/ui/input/index.js';
  import { cn } from '$lib/utils';
  import type { AccessFeature, AccessSource, RoleAccess } from '$lib/api/people';
  import { OWNER, rightKey, type RolesController } from '../state/roles-controller.svelte';
  import type { Reach } from '../reach';
  import MockupBadge from '$kit/ui/mockup-badge.svelte';
  import { CORE_AREAS, CORE_SOURCE, groupByArea } from '../core-features-mock';

  let { ctrl, role, holders }: { ctrl: RolesController; role: RoleAccess; holders: string[] } = $props();

  const REACH_OPTIONS: { value: Reach; label: string; title: string }[] = [
    { value: 'no', label: 'No', title: 'Not granted' },
    { value: 'own', label: 'Their own', title: "Only the person's own things" },
    { value: 'all', label: "Everyone's", title: "Everyone's things" }
  ];

  const locked = $derived(role.role_id === OWNER);
  const personalFeature = (s: AccessSource, f: AccessFeature) => f.rights.some((x) => ctrl.personal(s, f, x.id));
  const sourceLine = (s: AccessSource) =>
    s.kind === 'core' ? 'Set by HiroLeague itself' : `Declared by ${s.name} when it connects · ${s.connected ? 'connected' : 'not connected'}`;
</script>

<DetailPanel ariaLabel={`The role ${role.name}`} title={role.name} showCloseButton={false} onClose={() => {}} class="overflow-visible" bodyClass="overflow-visible grid gap-5 p-4">
  {#snippet headerActions()}
    {#if !role.built_in}
      <Button
        size="sm"
        variant="ghost"
        class="text-destructive"
        disabled={ctrl.busy}
        title={holders.length ? 'Give its people another role first.' : `Remove ${role.name}`}
        onclick={() => (ctrl.removeTarget = role)}
      >
        <Trash2 size={14} /> Remove
      </Button>
    {/if}
  {/snippet}

  <div class="grid gap-3 sm:grid-cols-[1fr_2fr]">
    <label class="grid gap-1">
      <span class="font-sans text-xs font-medium text-muted-foreground">Name</span>
      <Input
        class="font-sans"
        value={role.name}
        disabled={role.built_in || ctrl.busy}
        title={role.built_in ? `${role.name} is built in and keeps its name.` : ''}
        onchange={(e) => ctrl.rename(role, e.currentTarget.value)}
      />
    </label>
    <label class="grid gap-1">
      <span class="font-sans text-xs font-medium text-muted-foreground">What this role is for</span>
      <Input
        class="font-sans"
        value={role.says}
        maxlength={160}
        disabled={ctrl.busy}
        placeholder="One line, shown when you pick a role"
        onchange={(e) => ctrl.saveSays(role, e.currentTarget.value)}
      />
    </label>
  </div>

  <div class="grid gap-1.5">
    <SectionLabel level={4}>People with this role</SectionLabel>
    {#if holders.length}
      <div class="flex flex-wrap gap-1.5">
        {#each holders as name (name)}<Badge variant="secondary">{name}</Badge>{/each}
      </div>
    {:else}
      <p class="font-sans text-sm text-muted-foreground">Nobody yet. Give it to someone on People.</p>
    {/if}
  </div>

  {#if locked}
    <p class="flex items-center gap-2 font-sans text-xs text-muted-foreground">
      <Lock size={13} /> The owner has every right everywhere, except pages made for others (Home's My room), and can't be changed.
    </p>
  {/if}

  {#each ctrl.shown as s (s.id)}
    <section class="grid gap-1.5" aria-label={`${s.name}: rights`}>
      <SectionLabel level={4}>
        {s.name}
        {#snippet actions()}
          <!-- mockup: the core's own features (Permissions phase 2) -->
          {#if s.id === CORE_SOURCE}<MockupBadge />{/if}
          <span class="font-sans text-xs text-muted-foreground">{sourceLine(s)}</span>
        {/snippet}
      </SectionLabel>
      {#if s.features.length === 0}
        <p class="font-sans text-sm text-muted-foreground">Nothing to give here yet.</p>
      {:else}
        {@const g = ctrl.granted(role, s)}
        <div class="grid divide-y rounded-lg border">
          {#each groupByArea(s.features, s.id === CORE_SOURCE ? CORE_AREAS : {}) as group (group.area ?? group.features[0].id)}
          {#if group.area !== null}
            <!-- an area over its features (a permission is area.feature.action) -->
            <div class="bg-muted/40 px-3 py-1.5 font-sans text-xs font-semibold text-muted-foreground">{group.name}</div>
          {/if}
          {#each group.features as f (f.id)}
            <div class="grid gap-2 px-3 py-2.5 lg:grid-cols-[220px_1fr] lg:items-center">
              <span class={cn('flex items-center gap-2 font-sans text-sm font-medium', group.area !== null && 'pl-3')}>
                {f.name}
                {#if personalFeature(s, f)}
                  <span class="text-muted-foreground" title="About people's things: granted for their own or for everyone's">
                    <UserRound size={13} aria-label="About people's things" />
                  </span>
                {/if}
              </span>
              <div class="flex flex-wrap gap-x-4 gap-y-1.5">
                {#each f.rights as r (r.id)}
                  {#if ctrl.personal(s, f, r.id)}
                    <!-- a right about people's things: no, their own, or everyone's -->
                    <span class={cn('flex items-center gap-1.5 font-sans text-sm', locked && 'text-muted-foreground')} title={r.says}>
                      {r.name}
                      {#if locked}
                        <span class="text-xs">{f.not_for_owner ? '—' : "Everyone's"}</span>
                      {:else}
                        <Segmented
                          label={`${r.name}: whose`}
                          options={REACH_OPTIONS}
                          value={ctrl.reach(role, s, f, r.id)}
                          onchange={(v) => ctrl.setRightReach(role, s, f, r.id, v)}
                        />
                      {/if}
                    </span>
                  {:else}
                    <label class={cn('flex items-center gap-1.5 font-sans text-sm', locked && 'text-muted-foreground')} title={r.says}>
                      <Checkbox
                        checked={g.has(rightKey(f.id, r.id))}
                        disabled={locked || ctrl.busy}
                        onCheckedChange={(v) => ctrl.toggle(role, s, f, r.id, v)}
                      />
                      {r.name}
                    </label>
                  {/if}
                {/each}
              </div>
            </div>
          {/each}
          {/each}
        </div>
      {/if}
    </section>
  {/each}

  <p class="font-sans text-xs text-muted-foreground">
    Each change saves at once; the app follows within seconds. Hiro's own tools get their rights here later (Phase 10).
  </p>
</DetailPanel>
