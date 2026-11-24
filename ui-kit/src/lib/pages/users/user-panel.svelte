<script lang="ts">
	// Edit one user: their roles (one or several of those under Roles; their rights add up) or No access, and where the
	// app has a scope (HomeHiro's My room) and a role uses it, which areas and which of their own things it shows. The
	// user is a person in HiroLeague's family list, and the roles are set on them there.
	import { APP } from '$hiro-app/app';
	import { USERS } from '$hiro-app/users';
	import EditorSheet from '$kit/ui/editor-sheet.svelte';
	import CheckboxField from '$kit/ui/checkbox-field.svelte';
	import { Checkbox } from '$kit/components/ui/checkbox/index.js';
	import { dateTime } from '$kit/format/time';
	import { roleSummary } from './rules';
	import type { UsersAdmin } from './users-admin.svelte';

	let { ua }: { ua: UsersAdmin } = $props();
	const scope = USERS.scope;
	const u = $derived(ua.editing);
	const roles = $derived((ua.roles.data?.roles ?? []).map((r) => ({ id: r.id, name: r.name, says: r.says || roleSummary(r, ua.roles.data?.features ?? []) })));
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
		<h3 class="font-medium">Roles</h3>
		{#each roles as r (r.id)}
			{@const held = ua.form.value.roleIds.includes(r.id)}
			{#snippet says()}{r.says}{/snippet}
			<CheckboxField
				label={r.name}
				checked={held}
				disabled={ua.form.value.denied || (held && ua.form.value.roleIds.length === 1)}
				details={says}
				onchange={() => ua.toggleRole(r.id)}
			/>
		{/each}
		<p class="text-xs text-muted-foreground">Their rights add up. The roles are kept in HiroLeague's family list; what each may do in {APP.name} is under Roles.</p>
	</section>

	<section class="grid gap-2">
		<h3 class="font-medium">Access</h3>
		{#snippet noAccess()}They can't use {APP.name}. Their roles in HiroLeague stay as they are.{/snippet}
		<CheckboxField label="No access to {APP.name}" checked={ua.form.value.denied} details={noAccess} onchange={ua.toggleDenied} />
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
