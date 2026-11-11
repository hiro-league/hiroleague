<script lang="ts" generics="T extends string">
	// A choice from a longer list (hair styles, tops, shoes): small buttons that wrap onto more lines, the
	// picked one standing out.
	interface Props {
		options: readonly { id: T; label: string; title?: string }[];
		value: T;
		onchange: (v: T) => void;
		label: string; // what is chosen, for screen readers
	}
	let { options, value, onchange, label }: Props = $props();
</script>

<div class="flex flex-wrap gap-1.5" role="group" aria-label={label}>
	{#each options as o (o.id)}
		<button
			type="button"
			class={['rounded-md border px-2 py-1 text-xs', value === o.id ? 'border-primary bg-primary/10 font-medium text-foreground' : 'text-muted-foreground hover:text-foreground']}
			aria-pressed={value === o.id}
			title={o.title}
			onclick={() => onchange(o.id)}>{o.label}</button
		>
	{/each}
</div>
