<script lang="ts" generics="T extends string | number">
	// A choice from a longer list (hair styles, tops, shoes): small buttons that wrap onto more lines, the
	// picked one standing out.
	// UI kit, step 7b: built on shadcn-svelte's Toggle Group (single, outline), not on buttons of its own.
	import * as ToggleGroup from '$kit/components/ui/toggle-group/index.js';

	interface Props {
		options: readonly { id: T; label: string; title?: string }[];
		value: T;
		onchange: (v: T) => void;
		label: string; // what is chosen, for screen readers
	}
	let { options, value, onchange, label }: Props = $props();

	function pick(next: string) {
		if (!next) return; // one is always picked
		const o = options.find((o) => String(o.id) === next);
		if (o && o.id !== value) onchange(o.id);
	}
</script>

<ToggleGroup.Root type="single" variant="outline" spacing={1.5} bind:value={() => String(value), pick} aria-label={label} class="flex-wrap">
	{#each options as o (o.id)}
		<ToggleGroup.Item
			value={String(o.id)}
			title={o.title}
			class="h-auto min-w-0 rounded-md px-2 py-1 text-xs font-normal text-muted-foreground hover:bg-transparent data-[state=on]:border-primary data-[state=on]:bg-primary/10 data-[state=on]:font-medium data-[state=on]:text-foreground"
			>{o.label}</ToggleGroup.Item
		>
	{/each}
</ToggleGroup.Root>
