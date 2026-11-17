<script lang="ts">
	// Where toasts show (toast.svelte.ts): the bottom of the window, in the middle, clear of the error bar's corner.
	// Mounted once, in the shell.
	// UI kit, step 7b: shadcn-svelte's Sonner draws them. The kit's toast store still decides what shows and for how
	// long (the same words once, at most three, errors longer, the app's quiet rule), so Sonner is told to keep each
	// toast until the store lets it go; closing one in Sonner lets it go in the store too.
	import { toast as sonner } from 'svelte-sonner';
	import { Toaster } from '$kit/components/ui/sonner/index.js';
	import { toast } from './toast.svelte';

	const TONE = {
		success: 'border-success/40! [&_[data-icon]]:text-success',
		error: 'border-destructive/50! [&_[data-icon]]:text-destructive',
		warning: 'border-warning/50! [&_[data-icon]]:text-warning',
		info: 'border-primary/40! [&_[data-icon]]:text-primary'
	} as const;

	const shown = new Set<number>(); // the store's ids Sonner shows now (not state: only the effect reads it)

	$effect(() => {
		const now = new Set(toast.list.map((t) => t.id));
		for (const id of shown) {
			if (!now.has(id)) {
				shown.delete(id);
				sonner.dismiss(id);
			}
		}
		for (const t of toast.list) {
			if (shown.has(t.id)) continue;
			shown.add(t.id);
			sonner[t.kind](t.message, {
				id: t.id,
				duration: Number.POSITIVE_INFINITY,
				closeButton: true,
				onDismiss: () => toast.dismiss(t.id)
			});
		}
	});
</script>

<Toaster
	position="bottom-center"
	visibleToasts={3}
	toastOptions={{ classes: { success: TONE.success, error: TONE.error, warning: TONE.warning, info: TONE.info } }}
/>
