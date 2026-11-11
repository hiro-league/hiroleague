<script lang="ts">
	// A table column head that sorts on click, with an arrow for the way it is sorted (a faded one on columns not sorted
	// by). `children` replaces the label for a head that shows an icon; `sortable={false}` is a plain head.
	// UI kit, step 7: also the HiroLeague admin's header cell (title, aria-sort, plain heads).
	import type { Snippet } from 'svelte';
	import type { SortState } from '$kit/ui/sort.svelte';
	import * as Table from '$kit/components/ui/table/index.js';
	import { ArrowDown, ArrowUp, ArrowUpDown } from '@lucide/svelte';

	interface Props {
		sorter: SortState<string>;
		key: string;
		label?: string;
		title?: string; // what hovering the head says
		sortable?: boolean;
		class?: string;
		children?: Snippet;
	}
	let { sorter, key, label = '', title, sortable = true, class: className = '', children }: Props = $props();
</script>

<Table.Head class={className} aria-sort={sortable ? sorter.ariaSort(key) : undefined}>
	{#if sortable}
		<button
			type="button"
			class="inline-flex items-center gap-1 [text-transform:inherit] hover:text-foreground"
			{title}
			onclick={() => sorter.toggle(key)}
		>
			{#if children}{@render children()}{:else}{label}{/if}
			{#if sorter.key !== key || sorter.off}
				<ArrowUpDown class="size-3 opacity-40" />
			{:else if sorter.desc}
				<ArrowDown class="size-3" />
			{:else}
				<ArrowUp class="size-3" />
			{/if}
		</button>
	{:else if children}{@render children()}{:else}{label}{/if}
</Table.Head>
