<script lang="ts">
	// Settings → Roles (read-only since Phase 9a): the roles, who has each, and what each may do in the app, as HiroLeague
	// grants them. The roles themselves (new, renamed, removed), their lines and their rights change in HiroLeague's
	// People → Roles, one place for every app; the Edit links open it. Backend: auth/api.py.
	import { APP } from '$hiro-app/app';
	import { USERS } from '$hiro-app/users';
	import { Badge } from '$kit/components/ui/badge/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import * as Table from '$kit/components/ui/table/index.js';
	import ResourceView from '$kit/ui/resource-view.svelte';
	import { ExternalLink, Lock } from '@lucide/svelte';
	import { RolesAdmin } from './roles-admin.svelte';

	const ra = new RolesAdmin();
	const roles = $derived(ra.roles.data?.roles ?? []);
	const count = (rights: string[]) => ra.features.filter((f) => rights.some((k) => k.startsWith(`${f.id}.`))).length;
</script>

<div class="mb-4 flex flex-wrap items-center justify-between gap-2">
	<p class="max-w-3xl text-sm text-muted-foreground">
		What each role may do in {APP.name} is set in HiroLeague, with the roles and who has them, so it's in one place for every app. Each feature has
		its own rights (see it, change it, delete, run...), and a role has each one or not. Owner has everything{USERS.scope ? ` but ${USERS.scope.label}` : ''}.
	</p>
	{#if ra.editUrl()}
		<Button href={ra.editUrl()} target="_blank" rel="noopener"><ExternalLink /> Edit in HiroLeague</Button>
	{:else}
		<span class="text-xs text-muted-foreground">Set HiroLeague's admin address in Settings → HiroLeague for the Edit links.</span>
	{/if}
</div>

<ResourceView resource={ra.roles} errorTitle="Could not load the roles">
	<div class="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
		{#each roles as r (r.id)}
			<Card.Root class="gap-3">
				<Card.Header class="flex flex-row items-start gap-2">
					<div class="min-w-0 flex-1">
						<Card.Title class="flex items-center gap-2">
							{r.name}
							{#if r.built_in}<Badge variant="outline" class="gap-1 text-muted-foreground"><Lock class="size-3" /> built in</Badge>{/if}
							{#if r.core === false}<Badge variant="warning" title="Bring the family list into HiroLeague (Settings → HiroLeague) to make it there"
									>only in {APP.name}</Badge
								>{/if}
						</Card.Title>
						<Card.Description class="text-xs">{r.says || 'No line yet'}</Card.Description>
					</div>
					{#if ra.editUrl(r)}
						<Button size="sm" variant="ghost" class="text-muted-foreground" href={ra.editUrl(r)} target="_blank" rel="noopener" title="Edit {r.name} in HiroLeague"
							><ExternalLink class="size-4" /> Edit</Button
						>
					{/if}
				</Card.Header>
				<Card.Content class="text-xs text-muted-foreground">
					<div>{count(r.rights)} of {ra.features.length} features</div>
					<div>{r.users.length ? `${r.users.length === 1 ? '1 user' : `${r.users.length} users`}: ${r.users.join(', ')}` : 'Nobody has it yet'}</div>
				</Card.Content>
			</Card.Root>
		{/each}
	</div>

	{#if roles.length}
		<Card.Root>
			<Card.Header>
				<Card.Title class="text-base">What each role may do</Card.Title>
				<Card.Description>As HiroLeague grants it · Users and roles: owners only</Card.Description>
			</Card.Header>
			<Card.Content class="overflow-x-auto">
				<Table.Root>
					<Table.Header>
						<Table.Row class="text-left text-xs text-muted-foreground hover:bg-transparent">
							<Table.Head class="py-2 pr-3 pl-0 text-muted-foreground">Feature</Table.Head>
							{#each roles as r (r.id)}<Table.Head class="px-3 py-2 text-muted-foreground">{r.name}</Table.Head>{/each}
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each ra.features as f (f.id)}
							<Table.Row class="last:border-0">
								<Table.Cell class="py-2 pr-3 pl-0">{f.name}</Table.Cell>
								{#each roles as r (r.id)}
									{@const text = ra.rightsText(r, f)}
									<Table.Cell class={['px-3 py-2 text-xs whitespace-normal', !text && 'text-muted-foreground/40']}>{text || '—'}</Table.Cell>
								{/each}
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</Card.Content>
		</Card.Root>
	{/if}
</ResourceView>
