<script lang="ts">
	// The small "back to the default" icon beside a label: a field, a checkbox row, a panel's title. The caller decides
	// when it shows (only when the value differs from the default) and may fade it in on pointing (`class`).
	// UI kit, step 7: from the HiroLeague admin's reset dot; Field and CheckboxField draw this one too.
	import { RotateCcw } from '@lucide/svelte';
	import { cn } from '$kit/utils';

	let { onreset, label = 'Back to the default', class: className }: { onreset: () => void; label?: string; class?: string } = $props();
</script>

<button
	type="button"
	class={cn('inline-flex shrink-0 text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground', className)}
	title="Back to the default"
	aria-label={label}
	onclick={(e) => {
		e.stopPropagation(); // beside a label: don't reach the control it labels
		onreset();
	}}><RotateCcw class="size-3.5" /></button
>
