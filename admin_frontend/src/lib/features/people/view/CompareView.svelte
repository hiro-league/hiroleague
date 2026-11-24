<script lang="ts">
  /**
   * People → Compare: every role against every feature of the apps the filter shows, grouped by app. It only reads;
   * a role's name opens it on Roles, where it is changed.
   */
  import { UserRound } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Table from '$kit/components/ui/table/index.js';
  import { cn } from '$lib/utils';
  import type { AccessFeature, AccessSource, RoleAccess } from '$lib/api/people';
  import type { RolesController } from '../state/roles-controller.svelte';
  import { featureSummary } from '../reach';
  import MockupBadge from '$kit/ui/mockup-badge.svelte';
  import { CORE_AREAS, CORE_SOURCE, groupByArea } from '../core-features-mock';

  let { ctrl, onopen }: { ctrl: RolesController; onopen: (roleId: string) => void } = $props();

  const cellText = (r: RoleAccess, s: AccessSource, f: AccessFeature) => featureSummary(f.rights, ctrl.reaches(r, s, f));
  const personalFeature = (s: AccessSource, f: AccessFeature) => f.rights.some((x) => ctrl.personal(s, f, x.id));
</script>

{#if ctrl.error}
  <p class="font-sans text-sm text-destructive">{ctrl.error}</p>
{/if}

<div class="rounded-lg border">
  <Table.Root scroll={false} class="font-sans">
    <Table.Header class="sticky top-[calc(var(--app-top,0px)+var(--page-header,0px))] z-10 bg-card">
      <Table.Row class="hover:bg-transparent">
        <Table.Head class="h-auto px-3 py-2 text-xs text-muted-foreground">Feature</Table.Head>
        {#each ctrl.roles as r (r.role_id)}
          <Table.Head class="h-auto px-3 py-2 text-xs">
            <Button variant="link" size="inline" title={`Open ${r.name} on Roles`} onclick={() => onopen(r.role_id)}>{r.name}</Button>
          </Table.Head>
        {/each}
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each ctrl.shown as s (s.id)}
        <Table.Row class="bg-muted/40 hover:bg-muted/40">
          <Table.Cell colspan={ctrl.roles.length + 1} class="px-3 py-1.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
            <span class="flex items-center gap-2">
              {s.name}
              <!-- mockup: the core's own features (Permissions phase 2) -->
              {#if s.id === CORE_SOURCE}<MockupBadge class="normal-case" />{/if}
            </span>
          </Table.Cell>
        </Table.Row>
        {#each groupByArea(s.features, s.id === CORE_SOURCE ? CORE_AREAS : {}) as group (group.area ?? group.features[0].id)}
        {#if group.area !== null}
          <Table.Row class="hover:bg-transparent">
            <Table.Cell colspan={ctrl.roles.length + 1} class="px-3 pt-2 pb-1 text-xs font-semibold text-muted-foreground">{group.name}</Table.Cell>
          </Table.Row>
        {/if}
        {#each group.features as f (`${s.id}.${f.id}`)}
          <Table.Row>
            <Table.Cell class={cn('px-3 py-2 whitespace-normal', group.area !== null && 'pl-6')}>
              <span class="flex items-center gap-2">
                {f.name}
                {#if personalFeature(s, f)}
                  <span class="text-muted-foreground" title="About people's things: granted for their own or for everyone's">
                    <UserRound size={13} aria-label="About people's things" />
                  </span>
                {/if}
              </span>
            </Table.Cell>
            {#each ctrl.roles as r (r.role_id)}
              {@const text = cellText(r, s, f)}
              <Table.Cell class={cn('px-3 py-2 text-xs whitespace-normal', text === '—' && 'text-muted-foreground/50')}>{text}</Table.Cell>
            {/each}
          </Table.Row>
        {/each}
        {/each}
      {/each}
    </Table.Body>
  </Table.Root>
</div>
