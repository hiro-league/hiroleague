<script lang="ts">
	// Marks something shown but not working yet (a design to try, not a feature): a small dashed "Mockup" badge, with
	// what it will do on hover.
	// UI kit, step 7b: shadcn-svelte's Badge (outline), dashed and in the warning colour.
	import { Badge } from '$kit/components/ui/badge/index.js';
	import { cn } from '$kit/utils';

	let { title, class: className }: { title?: string; class?: string } = $props();
</script>

<Badge
	variant="outline"
	class={cn('h-auto rounded-sm border-dashed border-warning/60 px-1.5 py-px text-[10px] font-semibold tracking-wide text-warning uppercase', className)}
	title={title ?? 'A mockup: shown to try the design, it does nothing yet'}>Mockup</Badge
>
