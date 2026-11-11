<script lang="ts">
  /**
   * People → Roles (Phase 9a): what each role may do, set in one place for HiroLeague and every app.
   *
   * - Sub-tabs: "All roles" (every role against the features) and one per role (its line, who has it, its rights,
   *   rename and remove).
   * - Source pills: All, HiroLeague itself, then each extension that declared features. Under All each row
   *   carries a pill saying where it comes from.
   * - Each feature lists its rights; a role has each one or not. Changes save at once and the app follows.
   */
  import { Lock, Plus, Trash2 } from '@lucide/svelte';
  import Subtabs from '$kit/ui/subtabs.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import { Checkbox } from '$kit/components/ui/checkbox/index.js';
  import * as Table from '$kit/components/ui/table/index.js';
  import Segmented from '$kit/ui/segmented.svelte';
  import { Input } from '$kit/components/ui/input/index.js';
  import { cn } from '$lib/utils';
  import type { AccessFeature, AccessSource, Person, RoleAccess } from '$lib/api/people';
  import { ALL_ROLES, ALL_SOURCES, OWNER, rightKey, type RolesController } from '../state/roles-controller.svelte';

  let { ctrl, people }: { ctrl: RolesController; people: Person[] } = $props();

  const shown = $derived(ctrl.sourceId === ALL_SOURCES ? ctrl.sources : ctrl.sources.filter((s) => s.id === ctrl.sourceId));
  const rows = $derived(shown.flatMap((s) => s.features.map((f) => ({ s, f }))));
  const role = $derived(ctrl.roles.find((r) => r.role_id === ctrl.tab));

  const subtabs = $derived([
    { id: ALL_ROLES, label: 'All roles' },
    ...ctrl.roles.map((r) => ({ id: r.role_id, label: r.name, count: holders(r.role_id).length }))
  ]);

  function holders(roleId: string): string[] {
    return people.filter((p) => p.role_id === roleId).map((p) => p.name);
  }

  const countFor = (s: AccessSource) => (role ? (role.rights[s.id] ?? []).length : s.features.length);
  const sourceOptions = $derived([
    { value: ALL_SOURCES, label: 'All', count: ctrl.sources.reduce((n, s) => n + countFor(s), 0) },
    ...ctrl.sources.map((s) => ({ value: s.id, label: s.name, count: countFor(s) }))
  ]);

  const apps = $derived(ctrl.sources.filter((s) => s.kind === 'extension'));
  const sourceLine = $derived.by(() => {
    if (ctrl.sourceId === ALL_SOURCES) {
      return apps.length ? `HiroLeague and ${apps.map((a) => a.name).join(', ')} · ${rows.length} features` : 'HiroLeague only: no app has declared rights yet';
    }
    const s = shown[0];
    if (!s) return '';
    const rights = s.features.reduce((n, f) => n + f.rights.length, 0);
    return s.kind === 'core'
      ? `Set by HiroLeague itself · ${s.features.length} features, ${rights} rights`
      : `Declared by ${s.name} when it connects · ${s.connected ? 'connected' : 'not connected'} · ${s.features.length} features, ${rights} rights`;
  });

  function cellText(r: RoleAccess, s: AccessSource, f: AccessFeature): string {
    const g = ctrl.granted(r, s);
    const have = f.rights.filter((x) => g.has(rightKey(f.id, x.id)));
    if (have.length === 0) return '—';
    if (have.length === f.rights.length && f.rights.length > 1) return 'Everything';
    return have.map((x) => x.name).join(', ');
  }
</script>

{#snippet sourcePill(s: AccessSource)}
  <Badge variant="secondary" class="shrink-0">{s.name}</Badge>
{/snippet}

<Panel class="grid gap-4">
  <Subtabs ariaLabel="Roles" tabs={subtabs} active={ctrl.tab} onSelect={(id) => (ctrl.tab = id)} scrollable>
    {#snippet toolbar()}
      <Button size="sm" variant="outline" disabled={ctrl.busy} onclick={() => (ctrl.newName = '')}>
        <Plus size={14} /> New role
      </Button>
    {/snippet}
  </Subtabs>

  {#if ctrl.error}
    <p class="font-sans text-sm text-destructive">{ctrl.error}</p>
  {/if}

  <div class="flex flex-wrap items-center justify-between gap-3">
    <Segmented class="flex-wrap" label="Show rights for" options={sourceOptions} value={ctrl.sourceId} onchange={(id) => (ctrl.sourceId = id)} />
    <span class="font-sans text-xs text-muted-foreground">{sourceLine}</span>
  </div>

  {#if ctrl.tab === ALL_ROLES}
    <div class="overflow-x-auto rounded-lg border">
      <Table.Root scroll={false} class="font-sans">
        <Table.Header>
          <Table.Row class="hover:bg-transparent">
            <Table.Head class="h-auto px-3 py-2 text-xs text-muted-foreground">Feature</Table.Head>
            {#each ctrl.roles as r (r.role_id)}
              <Table.Head class="h-auto px-3 py-2 text-xs text-muted-foreground">
                <Button variant="link" size="inline" onclick={() => (ctrl.tab = r.role_id)}>{r.name}</Button>
              </Table.Head>
            {/each}
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each rows as { s, f } (`${s.id}.${f.id}`)}
            <Table.Row>
              <Table.Cell class="px-3 py-2 whitespace-normal">
                <span class="flex items-center gap-2">
                  {#if ctrl.sourceId === ALL_SOURCES}{@render sourcePill(s)}{/if}
                  {f.name}
                </span>
              </Table.Cell>
              {#each ctrl.roles as r (r.role_id)}
                {@const text = cellText(r, s, f)}
                <Table.Cell class={cn('px-3 py-2 text-xs whitespace-normal', text === '—' && 'text-muted-foreground/50')}>{text}</Table.Cell>
              {/each}
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </div>
  {:else if role}
    {@const locked = role.role_id === OWNER}
    <div class="grid gap-3 sm:grid-cols-[1fr_2fr_1fr] sm:items-end">
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
      <div class="flex items-end justify-between gap-2">
        <div class="grid gap-1">
          <span class="font-sans text-xs font-medium text-muted-foreground">People with this role</span>
          <span class="font-sans text-sm">{holders(role.role_id).join(', ') || 'Nobody yet'}</span>
        </div>
        {#if !role.built_in}
          <Button
            size="sm"
            variant="ghost"
            class="text-destructive"
            disabled={ctrl.busy}
            title={holders(role.role_id).length ? 'Give its people another role first.' : `Remove ${role.name}`}
            onclick={() => (ctrl.removeTarget = role)}
          >
            <Trash2 size={14} /> Remove
          </Button>
        {/if}
      </div>
    </div>

    {#if locked}
      <p class="flex items-center gap-2 font-sans text-xs text-muted-foreground">
        <Lock size={13} /> The owner has every right everywhere, except pages made for others (Home's My room), and can't be changed.
      </p>
    {/if}

    {#if rows.length === 0}
      <p class="font-sans text-sm text-muted-foreground">Nothing to give here yet.</p>
    {:else}
      <div class="grid divide-y rounded-lg border">
        {#each rows as { s, f } (`${s.id}.${f.id}`)}
          {@const g = ctrl.granted(role, s)}
          <div class="grid gap-2 px-3 py-2.5 sm:grid-cols-[300px_1fr] sm:items-center">
            <span class="flex items-center gap-2 font-sans text-sm font-medium">
              {#if ctrl.sourceId === ALL_SOURCES}{@render sourcePill(s)}{/if}
              {f.name}
            </span>
            <div class="flex flex-wrap gap-x-4 gap-y-1.5">
              {#each f.rights as r (r.id)}
                {@const k = rightKey(f.id, r.id)}
                <label class={cn('flex items-center gap-1.5 font-sans text-sm', locked && 'text-muted-foreground')} title={r.says}>
                  <Checkbox
                    checked={g.has(k)}
                    disabled={locked || ctrl.busy}
                    onCheckedChange={(v) => ctrl.toggle(role, s, f, r.id, v)}
                  />
                  {r.name}
                </label>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    {/if}
    <p class="font-sans text-xs text-muted-foreground">
      Each change saves at once; the app follows within seconds. Hiro's own tools get their rights here later (Phase 10).
    </p>
  {/if}
</Panel>
