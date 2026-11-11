<script lang="ts">
	// A small "?" that shows what something is, on hover or keyboard focus.
	import * as Tooltip from '$kit/components/ui/tooltip/index.js';
	import { CircleHelp } from '@lucide/svelte';

	let { text, label }: { text: string; label: string } = $props();
</script>

<Tooltip.Root>
	<Tooltip.Trigger class="inline-flex text-muted-foreground hover:text-foreground" aria-label="What is {label}?">
		<CircleHelp class="size-3.5" />
	</Tooltip.Trigger>
	<Tooltip.Content class="max-w-xs text-xs leading-relaxed">{text}</Tooltip.Content>
</Tooltip.Root>
