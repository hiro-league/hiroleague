<script lang="ts">
	// A search box: the magnifier inside, the text bound.
	import { Input } from '$kit/components/ui/input/index.js';
	import { Search } from '@lucide/svelte';

	let { value = $bindable(''), placeholder = 'Search…', class: cls = 'min-w-48 flex-1' }: { value?: string; placeholder?: string; class?: string } = $props();
</script>

<div class="relative {cls}">
	<Search class="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
	<Input class="pl-8" {placeholder} bind:value />
</div>
