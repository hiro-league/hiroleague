<script lang="ts" generics="T">
	import type { Sorter } from '$kit/ui/sort.svelte';
	import * as Table from '$kit/components/ui/table/index.js';
	import { ArrowDown, ArrowUp, ArrowUpDown } from '@lucide/svelte';

	let { sorter, key, label, class: className = '' }: { sorter: Sorter<T>; key: string; label: string; class?: string } =
		$props();
</script>

<Table.Head class={className}>
	<button type="button" class="inline-flex items-center gap-1 hover:text-foreground" onclick={() => sorter.toggle(key)}>
		{label}
		{#if sorter.key !== key}
			<ArrowUpDown class="size-3 opacity-40" />
		{:else if sorter.desc}
			<ArrowDown class="size-3" />
		{:else}
			<ArrowUp class="size-3" />
		{/if}
	</button>
</Table.Head>
