<script lang="ts">
	// Edit one user: their role (the roles under Roles, or No access), and where the app has a scope (HomeHiro's My
	// room) and the role uses it, which areas and which of their own things it shows. The user is a person in
	// HiroLeague's family list, and the role is set on them there.
	import { APP } from '$hiro-app/app';
	import { USERS } from '$hiro-app/users';
	import EditorSheet from '$kit/ui/editor-sheet.svelte';
	import { Checkbox } from '$kit/components/ui/checkbox/index.js';
	import { dateTime } from '$kit/format/time';
	import { NO_ACCESS, roleSummary } from './rules';
	import type { UsersAdmin } from './users-admin.svelte';

	let { ua }: { ua: UsersAdmin } = $props();
	const scope = USERS.scope;
	const u = $derived(ua.editing);
	const choices = $derived([
		...(ua.roles.data?.roles ?? []).map((r) => ({ id: r.id, name: r.name, says: r.says || roleSummary(r, ua.roles.data?.features ?? []) })),
		{ id: NO_ACCESS, name: 'No access', says: `They can't use ${APP.name}.` }
	]);
</script>

{#snippet personLine()}
	{#if scope}{u?.person ? `${scope.linkedLabel}: ${u.person.name}` : scope.notLinked}{/if}
{/snippet}

<EditorSheet
	bind:open={ua.open}
	title={u?.name ?? ''}
	description={scope ? personLine : undefined}
	saveLabel="Save"
	canSave={ua.canSave}
	dirty={ua.dirty}
	error={ua.form.action.error}
	onsave={ua.save}
>
	<section class="grid gap-2">
		<h3 class="font-medium">Role</h3>
		{#each choices as r (r.id)}
			<button
				type="button"
				class={['rounded-md border p-3 text-left', ua.form.value.choice === r.id ? 'border-primary bg-muted' : 'hover:bg-muted/50']}
				aria-pressed={ua.form.value.choice === r.id}
				onclick={() => ua.pick(r.id)}
			>
				<div class="font-medium">{r.name}</div>
				<div class="text-xs text-muted-foreground">{r.says}</div>
			</button>
		{/each}
		<p class="text-xs text-muted-foreground">The role is kept in HiroLeague's family list; what it may do in {APP.name} is under Roles.</p>
	</section>

	{#if scope && ua.needsScope}
		<section class="grid gap-2">
			<h3 class="font-medium">{scope.label}: rooms</h3>
			<p class="text-xs text-muted-foreground">{scope.areasHelp}</p>
			{#each ua.rooms as a (a.id)}
				<label class="flex items-center gap-2">
					<Checkbox checked={ua.form.value.areas.includes(a.id)} onCheckedChange={() => ua.toggle('areas', a.id)} />
					{a.name}
				</label>
			{/each}
		</section>
		<section class="grid gap-2">
			<h3 class="font-medium">{scope.label}: their things</h3>
			{#if u?.person_things?.length}
				<p class="text-xs text-muted-foreground">{scope.thingsHelp}</p>
				{#each u.person_things as t (t.id)}
					<label class="flex items-center gap-2">
						<Checkbox checked={ua.form.value.things.includes(t.id)} onCheckedChange={() => ua.toggle('things', t.id)} />
						{t.name}
					</label>
				{/each}
			{:else}
				<p class="text-xs text-muted-foreground">{scope.noThings}</p>
			{/if}
		</section>
		{#if ua.form.value.areas.length + ua.form.value.things.length === 0}<p class="text-xs text-warning">Pick at least one room or thing, or their {scope.label} is empty.</p>{/if}
	{/if}

	{#if u}
		<section class="grid gap-1 text-xs text-muted-foreground">
			<h3 class="text-sm font-medium text-foreground">Lately</h3>
			<p>First came in {dateTime(u.first_seen)}. Last here {dateTime(u.last_seen)}, {u.last_device}.</p>
		</section>
	{/if}
</EditorSheet>
