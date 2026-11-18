<script lang="ts">
	// A tile that leads somewhere: an icon in its colour, a title and a line under it, an arrow, and what it holds
	// (counts, a short list). `accent`: primary, or a category number.
	// UI kit, step 7d: the tile is shadcn-svelte's Card (its header, title, description, action and content) inside
	// the link; the accent colour and the hover are the kit's.
	import type { Component, Snippet } from 'svelte';
	import { ArrowRight } from '@lucide/svelte';
	import * as Card from '$kit/components/ui/card/index.js';
	import { cn } from '$kit/utils';
	import { catVar } from '$kit/ui/category';

	/** `primary`, or a category number (1 … 8) for a tile's own colour. */
	type Accent = 'primary' | number;

	let {
		href,
		title,
		subtitle,
		icon: Icon,
		accent = 'primary',
		children
	}: {
		href: string;
		title: string;
		subtitle: string;
		icon: Component<{ size?: number }>;
		accent?: Accent;
		children?: Snippet;
	} = $props();

	const tone = $derived(accent === 'primary' ? 'var(--primary)' : catVar(accent));
</script>

<a class="group block rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none" style:--tile={tone} {href}>
	<Card.Root
		class={cn(
			'min-h-36 gap-3 shadow-sm transition-colors group-hover:ring-(--tile)/50',
			accent === 'primary' ? 'group-hover:bg-secondary/20' : 'group-hover:bg-(--tile)/5'
		)}
	>
		<Card.Header class="flex items-center gap-3">
			<span class="rounded-full bg-(--tile)/15 p-2.5 text-(--tile)">
				<Icon size={20} />
			</span>
			<div class="grid gap-0.5">
				<Card.Title class="font-sans text-base font-semibold">{title}</Card.Title>
				<Card.Description class="font-sans text-xs font-semibold">{subtitle}</Card.Description>
			</div>
			<Card.Action class="ml-auto self-start">
				<ArrowRight class="mt-1 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-(--tile)" size={18} />
			</Card.Action>
		</Card.Header>
		{#if children}
			<Card.Content class="grid gap-3">
				{@render children()}
			</Card.Content>
		{/if}
	</Card.Root>
</a>
