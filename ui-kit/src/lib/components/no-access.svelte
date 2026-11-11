<script lang="ts">
	// What someone the app knows but hasn't given a role sees: new and waiting, or given No access by the
	// owner. It asks again every half minute, so it opens by itself once the owner picks a role.
	// UI kit, step 1: the app's name, icon and words come from lib/app/app.ts, so this file is the same in every Hiro app.
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import { APP } from '$hiro-app/app';
	import { poll } from '$kit/state/poll.svelte';
	import { who } from '$kit/state/who.svelte';
	import { DoorClosed, Hourglass } from '@lucide/svelte';

	const denied = $derived(who.me?.state === 'denied');
	poll(who.load, 30_000);
</script>

<div class="flex min-h-svh items-center justify-center p-4">
	<Card.Root class="w-full max-w-sm text-center">
		<Card.Header class="items-center">
			{#if denied}<DoorClosed class="mx-auto mb-2 size-10 text-muted-foreground" />{:else}<Hourglass class="mx-auto mb-2 size-10 text-muted-foreground" />{/if}
			<Card.Title class="text-lg">Hi {who.me?.name}</Card.Title>
			<Card.Description>{denied ? `You don't have access to ${APP.name}.` : `You can't use ${APP.name} yet.`}</Card.Description>
		</Card.Header>
		<Card.Content class="grid gap-3 text-sm">
			<!-- Phase 8: the backend says why someone waits (e.g. their HA user isn't linked to a person in the family list) -->
			{#if !denied && who.me?.reason}<p>{who.me.reason} Once they do, this page opens by itself.</p>
			{:else if !denied}<p>The owner decides who can use {APP.name}. Once they give you access, this page opens by itself.</p>{/if}
			<p class="text-xs text-muted-foreground">
				{who.me?.way === 'web' ? `Signed in through HiroLeague as ${who.me?.name}.` : `${APP.signIn.otherWay} as ${who.me?.name}.`}
			</p>
			{#if who.me?.way === 'web'}<Button variant="outline" onclick={who.signOut}>Sign out</Button>{/if}
		</Card.Content>
	</Card.Root>
</div>
