<script lang="ts">
	// Someone's picture in a circle, or their initials when there is none (or it fails to load).
	// UI kit, step 7b: built on shadcn-svelte's Avatar (its image falls back by itself); the initials and the caller's
	// size and text classes are the kit's (the initials take the caller's text size, not the Avatar's own).
	import * as Avatar from '$kit/components/ui/avatar/index.js';
	import { cn } from '$kit/utils';

	let { name, src = null, class: className = 'size-10' }: { name: string; src?: string | null; class?: string } = $props();
	const initials = $derived(
		name
			.split(/\s+/)
			.filter(Boolean)
			.slice(0, 2)
			.map((w) => w[0].toUpperCase())
			.join('')
	);
</script>

<Avatar.Root class={cn('size-10', className)} title={name}>
	{#if src}<Avatar.Image {src} alt={name} class="object-cover" />{/if}
	<Avatar.Fallback class="font-medium text-[length:inherit]">{initials}</Avatar.Fallback>
</Avatar.Root>
