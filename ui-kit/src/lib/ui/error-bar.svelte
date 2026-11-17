<script lang="ts">
	// At the bottom of every page: errors nobody caught (app-errors.svelte.ts), each until dismissed.
	// Mounted once, in the layout; it listens to the window for them.
	// UI kit, step 7b: each error is shadcn-svelte's Alert (destructive), not a box of its own.
	import * as Alert from '$kit/components/ui/alert/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import { TriangleAlert, X } from '@lucide/svelte';
	import { appErrors } from './app-errors.svelte';

	$effect(() => {
		const rejected = (e: PromiseRejectionEvent) => appErrors.add(e.reason);
		const thrown = (e: ErrorEvent) => appErrors.add(e.error ?? e.message);
		window.addEventListener('unhandledrejection', rejected);
		window.addEventListener('error', thrown);
		return () => {
			window.removeEventListener('unhandledrejection', rejected);
			window.removeEventListener('error', thrown);
		};
	});
</script>

{#if appErrors.list.length}
	<div class="fixed right-4 bottom-4 z-50 grid w-[min(28rem,calc(100vw-2rem))] gap-2" role="alert">
		{#each appErrors.list as e (e.id)}
			<Alert.Root variant="destructive" role="none" class="border-destructive/50 bg-background p-3 text-foreground shadow-lg has-[>svg]:grid-cols-[auto_1fr_auto]">
				<TriangleAlert />
				<Alert.Title class="text-foreground">Something went wrong{e.count > 1 ? ` (${e.count}×)` : ''}</Alert.Title>
				<Alert.Description class="break-words text-muted-foreground">{e.message}</Alert.Description>
				<Button variant="ghost" size="icon-sm" class="col-start-3 row-span-2 row-start-1 -my-1 text-muted-foreground" title="Dismiss" onclick={() => appErrors.dismiss(e.id)}><X /></Button>
			</Alert.Root>
		{/each}
	</div>
{/if}
