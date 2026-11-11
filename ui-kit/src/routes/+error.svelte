<script lang="ts">
	// A page that could not be opened: why, and the way on (try again, or the home page).
	// UI kit, step 1: the app's name, icon and words come from lib/app/app.ts, so this file is the same in every Hiro app.
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { APP } from '$hiro-app/app';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
</script>

<Card.Root class="max-w-xl">
	<Card.Header>
		<Card.Title>{page.status === 404 ? 'Page not found' : "This page couldn't open"}</Card.Title>
		<Card.Description>{page.error?.message}</Card.Description>
	</Card.Header>
	<Card.Footer class="gap-2">
		{#if page.status !== 404}<Button onclick={() => location.reload()}>Try again</Button>{/if}
		<Button variant="outline" href={resolve('/')}>{APP.homeTitle}</Button>
	</Card.Footer>
</Card.Root>
