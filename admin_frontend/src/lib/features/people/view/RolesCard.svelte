<script lang="ts">
  /**
   * People → Roles (Phase 8): one switch per role, "Can open HiroLeague's settings". Owner always can.
   * Someone whose role is off still signs in (for Home and the other apps) but sees only the Apps card.
   */
  import Badge from '$lib/components/ui/badge.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import type { PeopleController } from '../state/people-controller.svelte';

  let { ctrl }: { ctrl: PeopleController } = $props();

  const counts = $derived(
    ctrl.people.reduce<Record<string, number>>((acc, p) => {
      acc[p.role_id] = (acc[p.role_id] ?? 0) + 1;
      return acc;
    }, {})
  );
</script>

<SectionCard class="grid gap-4">
  <div class="grid gap-1">
    <h2 class="font-sans text-base font-semibold">Roles</h2>
    <p class="font-sans text-sm text-muted-foreground">
      One sign-in for HiroLeague and its apps. A role that can't open HiroLeague's settings sees only the Apps
      card here. What each role may do in Home is set in HomeHiro.
    </p>
  </div>
  <div class="grid divide-y rounded-lg border">
    {#each ctrl.roles as role (role.role_id)}
      {@const locked = role.role_id === 'owner'}
      <div class="grid grid-cols-[1fr_auto] items-center gap-3 px-4 py-3 sm:grid-cols-[160px_110px_1fr]">
        <span class="flex items-center gap-2 font-sans text-sm font-semibold">
          {role.name}
          {#if role.built_in}<Badge variant="secondary">built in</Badge>{/if}
        </span>
        <span class="font-sans text-xs text-muted-foreground">
          {counts[role.role_id] ?? 0} {(counts[role.role_id] ?? 0) === 1 ? 'person' : 'people'}
        </span>
        <label
          class="col-span-2 flex items-center gap-2 font-sans text-sm sm:col-span-1"
          title={locked ? 'The owner always can.' : ''}
        >
          <input
            type="checkbox"
            checked={role.admin}
            disabled={locked || ctrl.busy}
            onchange={(event) => void ctrl.setRoleOpensSettings(role, event.currentTarget.checked)}
          />
          <span class:text-muted-foreground={locked}>Can open HiroLeague's settings</span>
        </label>
      </div>
    {/each}
  </div>
</SectionCard>
