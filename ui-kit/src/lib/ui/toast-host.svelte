<script lang="ts">
	// Where toasts show (toast.svelte.ts): the bottom of the window, in the middle, clear of the error bar's corner.
	// Mounted once, in the shell.
	import { CircleCheck, Info, TriangleAlert, X } from '@lucide/svelte';
	import { toast } from './toast.svelte';

	const TONE = {
		success: 'border-success/40 [&_[data-icon]]:text-success',
		error: 'border-destructive/50 [&_[data-icon]]:text-destructive',
		warning: 'border-warning/50 [&_[data-icon]]:text-warning',
		info: 'border-primary/40 [&_[data-icon]]:text-primary'
	} as const;
</script>

{#if toast.list.length}
	<div class="pointer-events-none fixed bottom-4 left-1/2 z-[60] grid w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 gap-2">
		{#each toast.list as t (t.id)}
			{@const Icon = t.kind === 'success' ? CircleCheck : t.kind === 'info' ? Info : TriangleAlert}
			<div
				class={['pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-popover p-3 text-sm text-popover-foreground shadow-lg', TONE[t.kind]]}
				role={t.kind === 'error' ? 'alert' : 'status'}
			>
				<Icon data-icon class="mt-0.5 size-4 shrink-0" />
				<div class="min-w-0 flex-1 break-words">{t.message}</div>
				<button type="button" class="text-muted-foreground hover:text-foreground" aria-label="Dismiss" onclick={() => toast.dismiss(t.id)}><X class="size-4" /></button>
			</div>
		{/each}
	</div>
{/if}
