<script lang="ts">
	// At the bottom of every page: errors nobody caught (app-errors.svelte.ts), each until dismissed.
	// Mounted once, in the layout; it listens to the window for them.
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
			<div class="flex items-start gap-2 rounded-lg border border-destructive/50 bg-background p-3 text-sm shadow-lg">
				<TriangleAlert class="mt-0.5 size-4 shrink-0 text-destructive" />
				<div class="min-w-0 flex-1">
					<div class="font-medium">Something went wrong{e.count > 1 ? ` (${e.count}×)` : ''}</div>
					<div class="break-words text-muted-foreground">{e.message}</div>
				</div>
				<Button variant="ghost" size="icon-sm" title="Dismiss" onclick={() => appErrors.dismiss(e.id)}><X /></Button>
			</div>
		{/each}
	</div>
{/if}
