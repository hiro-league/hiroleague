<script lang="ts">
	// Settings → Roles (read-only since Phase 9a): one table, each role a column with who holds it (one person may hold
	// several) and a link to edit it in HiroLeague, each feature a row with what each role may do there, as HiroLeague
	// grants them. The roles themselves (new, renamed, removed), their lines and their rights change in HiroLeague's
	// People → Roles, one place for every app; the Edit links open it. Backend: auth/api.py.
	import { APP } from '$hiro-app/app';
	import { USERS } from '$hiro-app/users';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import * as Table from '$kit/components/ui/table/index.js';
	import ResourceView from '$kit/ui/resource-view.svelte';
	import { ExternalLink, Lock } from '@lucide/svelte';
	import { RolesAdmin } from './roles-admin.svelte';

	const ra = new RolesAdmin();
	const roles = $derived(ra.roles.data?.roles ?? []);
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
	{#if roles.length}
		<Card.Root>
			<Card.Header>
				<Card.Title class="flex items-center gap-2 text-base">What each role may do</Card.Title>
				<Card.Description>As HiroLeague grants it · Users and roles: owners only</Card.Description>
			</Card.Header>
			<Card.Content class="overflow-x-auto">
				<Table.Root>
					<Table.Header>
						<Table.Row class="text-left text-xs text-muted-foreground hover:bg-transparent">
							<Table.Head class="py-2 pr-3 pl-0 align-bottom text-muted-foreground">Feature</Table.Head>
							{#each roles as r (r.id)}
								<Table.Head class="h-auto px-3 py-2 align-bottom whitespace-normal">
									<div class="flex items-center gap-1 font-medium text-foreground">
										{r.name}
										{#if r.built_in}<Lock class="size-3 text-muted-foreground" aria-label="built in" />{/if}
										{#if ra.editUrl(r)}
											<Button size="icon" variant="ghost" class="size-6 text-muted-foreground" href={ra.editUrl(r)} target="_blank" rel="noopener" title="Edit {r.name} in HiroLeague"
												><ExternalLink class="size-3.5" /></Button
											>
										{/if}
									</div>
									<div class="font-normal text-muted-foreground" title={r.says}>{r.users.length ? r.users.join(', ') : 'Nobody yet'}</div>
								</Table.Head>
							{/each}
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
