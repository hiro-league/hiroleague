<script lang="ts">
	// Someone's picture in a circle, or their initials when there is none (or it fails to load).
	import { cn } from '$kit/utils';

	let { name, src = null, class: className = 'size-10' }: { name: string; src?: string | null; class?: string } = $props();
	let failed = $state(false);
	const initials = $derived(
		name
			.split(/\s+/)
			.filter(Boolean)
			.slice(0, 2)
			.map((w) => w[0].toUpperCase())
			.join('')
	);
</script>

{#if src && !failed}
	<img {src} alt={name} class={cn('shrink-0 rounded-full object-cover', className)} onerror={() => (failed = true)} />
{:else}
	<span class={cn('flex shrink-0 items-center justify-center rounded-full bg-muted font-medium text-muted-foreground', className)} title={name}
		>{initials}</span
	>
{/if}
