<script lang="ts">
  /**
   * People → Roles: the roles at the left (each with how many people hold it), the one picked at the right with what
   * it is for, who holds it and its rights. Comparing every role is the Compare tab; which apps are shown is the
   * filter under the page's header.
   */
  import { Lock } from '@lucide/svelte';
  import MasterDetail from '$kit/ui/master-detail.svelte';
  import { cn } from '$lib/utils';
  import type { Person } from '$lib/api/people';
  import { OWNER, type RolesController } from '../state/roles-controller.svelte';
  import RolePanel from './RolePanel.svelte';

  let { ctrl, people, rolesOf }: { ctrl: RolesController; people: Person[]; rolesOf: (person: Person) => string[] } = $props();

  const holders = (roleId: string) => people.filter((p) => rolesOf(p).includes(roleId)).map((p) => p.name);
  const picked = $derived(ctrl.roles.find((r) => r.role_id === ctrl.role));

  // Another role starts at the top of its rights: the list stays in view, the page doesn't keep the last role's place.
  function pick(roleId: string) {
    if (roleId === ctrl.role) return;
    ctrl.role = roleId;
    window.scrollTo({ top: 0 });
  }
</script>

{#if ctrl.error}
  <p class="font-sans text-sm text-destructive">{ctrl.error}</p>
{/if}

<MasterDetail detailOpen={picked !== undefined} scroll="page" splitClass="min-[900px]:grid-cols-[220px_minmax(0,1fr)]">
  {#snippet list()}
    <!-- the list stays in view while the role's rights scroll -->
    <nav aria-label="Roles" class="sticky top-[calc(var(--app-top,0px)+var(--page-header,0px)+0.5rem)] grid gap-1 self-start rounded-md border bg-card p-1.5">
      {#each ctrl.roles as r (r.role_id)}
        {@const n = holders(r.role_id).length}
        <button
          type="button"
          aria-current={r.role_id === ctrl.role ? 'true' : undefined}
          class={cn(
            'grid gap-0.5 rounded-md px-2.5 py-2 text-left font-sans hover:bg-muted/60',
            r.role_id === ctrl.role && 'bg-primary/10 hover:bg-primary/10'
          )}
          onclick={() => pick(r.role_id)}
        >
          <span class="flex items-center gap-1.5 text-sm font-medium">
            {#if r.role_id === OWNER}<Lock size={12} class="text-muted-foreground" />{/if}
            {r.name}
            <span class="ml-auto text-xs font-normal tabular-nums text-muted-foreground" title="People with this role">{n}</span>
          </span>
          {#if r.says}<span class="line-clamp-2 text-xs text-muted-foreground">{r.says}</span>{/if}
        </button>
      {/each}
    </nav>
  {/snippet}
  {#snippet detail()}
    {#if picked}
      {#key picked.role_id}
        <RolePanel {ctrl} role={picked} holders={holders(picked.role_id)} />
      {/key}
    {/if}
  {/snippet}
</MasterDetail>
