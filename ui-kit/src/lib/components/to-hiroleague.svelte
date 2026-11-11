<script lang="ts">
	// What a signed-out visitor sees (Phase 8: one sign-in): for a blink, before the app sends them on to HiroLeague's
	// sign-in page, which sends them back here signed in. It stays when the sign-in came back with a problem (it says
	// why), and after signing out here (HiroLeague, still signed in, would send them straight back).
	// UI kit, step 1: the app's name, icon and words come from lib/app/app.ts, so this file is the same in every Hiro app.
	// (HomeHiro's words add its other way in: inside the HA app this page never shows, HA's add-on says who you are.)
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import { APP } from '$hiro-app/app';
	import { who } from '$kit/state/who.svelte';
	import { LogIn, TriangleAlert } from '@lucide/svelte';

	const failed = $derived(page.url.searchParams.get('signin_error'));
	const going = $derived(!failed && !who.signedOut);

	onMount(() => {
		if (going) who.signIn();
	});
</script>

<div class="flex min-h-svh items-center justify-center p-4">
	<Card.Root class="w-full max-w-sm text-center">
		<Card.Header class="items-center">
			<APP.icon class="mx-auto mb-2 size-10 text-primary" />
			<Card.Title class="text-xl">{APP.name}</Card.Title>
			<Card.Description>
				{going ? 'Taking you to HiroLeague to sign in…' : who.signedOut ? `You're signed out of ${APP.name}.` : "Signing in didn't work."}
			</Card.Description>
		</Card.Header>
		<Card.Content class="grid gap-4">
			{#if failed}<p class="flex gap-2 text-left text-sm text-destructive"><TriangleAlert class="size-4 shrink-0" />{failed}</p>{/if}
			<Button size="lg" class="w-full" onclick={who.signIn}><LogIn /> Sign in at HiroLeague</Button>
			<p class="text-xs text-muted-foreground">{APP.signIn.about}</p>
			{#if APP.signIn.also}<p class="text-xs text-muted-foreground">{APP.signIn.also}</p>{/if}
		</Card.Content>
	</Card.Root>
</div>
