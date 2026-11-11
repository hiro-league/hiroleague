<script lang="ts">
	// Settings → Users: everyone who has opened the app (people in HiroLeague's family list), their role, and how they
	// came in last. Anyone without a role waits at the top. Backend: auth/api.py.
	import { APP } from '$hiro-app/app';
	import { USERS } from '$hiro-app/users';
	import { Badge } from '$kit/components/ui/badge/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import EmptyState from '$kit/ui/empty-state.svelte';
	import ResourceView from '$kit/ui/resource-view.svelte';
	import PersonAvatar from '$kit/ui/avatar.svelte';
	import { dateTime } from '$kit/format/time';
	import { Pencil, UserPlus } from '@lucide/svelte';
	import { hasScope } from './rules';
	import type { AppUser } from './types';
	import UserPanel from './user-panel.svelte';
	import { UsersAdmin } from './users-admin.svelte';

	const ua = new UsersAdmin();

	const scope = USERS.scope;
	const way = (u: AppUser) => USERS.ways[u.last_way] ?? u.last_way;
	const seen = (u: AppUser) => `${dateTime(u.last_seen)} · ${way(u)}, ${u.last_device}`;
	const scopeText = (u: AppUser) =>
		[...(u.areas ?? []).map((id) => ua.rooms.find((a) => a.id === id)?.name ?? id), ...(u.things ?? []).map((id) => u.person_things?.find((t) => t.id === id)?.name ?? id)].join(
			' · '
		) || 'nothing picked';
</script>

<p class="mb-4 max-w-3xl text-sm text-muted-foreground">{USERS.intro}</p>

<ResourceView resource={ua.users} errorTitle="Could not load the users">
	{#if ua.waiting.length}
		<Card.Root class="mb-4 border-warning/50">
			<Card.Header>
				<Card.Title class="flex items-center gap-2 text-base"><UserPlus class="size-5 text-warning" /> Waiting for a role</Card.Title>
				<Card.Description>They opened {APP.name}, but {APP.name} doesn't have their role yet. Until they have one they can't use it.</Card.Description>
			</Card.Header>
			<Card.Content class="grid gap-2">
				{#each ua.waiting as u (u.id)}
					<div class="flex flex-wrap items-center gap-3 rounded-md border p-3">
						<PersonAvatar name={u.name} />
						<div class="min-w-0 flex-1">
							<div class="font-medium">{u.name}</div>
							<div class="text-xs text-muted-foreground">
								First came in {dateTime(u.first_seen)} from the {way(u)}, {u.last_device}{scope && !u.person ? scope.waitingNotLinked : ''}
							</div>
						</div>
						<Button size="sm" onclick={() => ua.edit(u)}>Pick a role</Button>
					</div>
				{/each}
			</Card.Content>
		</Card.Root>
	{/if}

	{#if ua.known.length}
		<Card.Root class="py-2">
			<Card.Content class="divide-y px-2">
				{#each ua.known as u (u.id)}
					<div class="flex flex-wrap items-center gap-3 px-2 py-3">
						<PersonAvatar name={u.name} />
						<div class="min-w-40 flex-1">
							<div class="flex items-center gap-2 font-medium">
								{u.name}
								<Badge variant={u.role_id === 'owner' ? 'default' : u.denied ? 'outline' : 'secondary'} class={u.denied ? 'text-muted-foreground' : ''}>{ua.roleName(u)}</Badge>
							</div>
							{#if scope}
								<div class="text-xs text-muted-foreground">
									{#if hasScope(ua.roleOf(u.role_id), scope.feature)}{scope.label}: {scopeText(u)}{:else if u.person}{scope.linkedLabel}: {u.person.name}{/if}
								</div>
							{/if}
						</div>
						<div class="text-right text-xs text-muted-foreground max-sm:w-full max-sm:text-left">
							<div>Last here</div>
							<div class="text-foreground">{seen(u)}</div>
						</div>
						<Button size="icon" variant="ghost" class="size-9 text-muted-foreground" title="Edit {u.name}" onclick={() => ua.edit(u)}><Pencil class="size-5" /></Button>
					</div>
				{/each}
			</Card.Content>
		</Card.Root>
	{:else if !ua.waiting.length}
		<EmptyState message="Nobody else has opened {APP.name} yet." />
	{/if}
</ResourceView>

<UserPanel {ua} />
