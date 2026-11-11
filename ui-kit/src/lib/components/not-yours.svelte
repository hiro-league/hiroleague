<script lang="ts">
	// A page outside the user's role (an old link, a typed address): says so, and offers the first page
	// they have. The backend refuses the page's calls anyway (auth/guard.py).
	import { resolve } from '$app/paths';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import { APP } from '$hiro-app/app'; // UI kit, step 1: the app's name, icon and words come from lib/app/app.ts, so this file is the same in every Hiro app.
	import { firstPage } from '$kit/state/pages';
	import { who } from '$kit/state/who.svelte';
	import { DoorClosed } from '@lucide/svelte';

	const start = $derived(firstPage(who.me));
</script>

<Card.Root class="mx-auto mt-10 max-w-sm text-center">
	<Card.Header class="items-center">
		<DoorClosed class="mx-auto mb-2 size-10 text-muted-foreground" />
		<Card.Title class="text-lg">This page isn't part of your {APP.name}</Card.Title>
		<Card.Description>Your role ({who.me?.role_name}) doesn't include it.</Card.Description>
	</Card.Header>
	{#if start}
		<Card.Content>
			<Button href={resolve(start as '/')}>Go to your start page</Button>
		</Card.Content>
	{/if}
</Card.Root>
