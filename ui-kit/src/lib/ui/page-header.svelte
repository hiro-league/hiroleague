<script lang="ts">
	// The top of every page: its title with its tabs on the same line (they scroll sideways when the window is too
	// narrow, never drop to a line of their own), the page's actions to the right, and an optional row under them
	// (inner tabs, filters). It stays at the top of the window while the page scrolls, under the app's top bar when
	// it has one (--app-top, set by the shell). Its height is published as --page-header, so a bar further down the
	// page can stick right under it (StickyBar).
	// UI kit, step 3: `adornment` (a small thing beside the title: an open-folder icon), `description` (one quiet
	// line under the title) and `details` (the same place, for more than words) came with the HiroLeague admin's pages.
	import type { Snippet } from 'svelte';
	import { ArrowLeft } from '@lucide/svelte';

	interface Props {
		title?: string;
		/** A link back to where this page was opened from. UI kit, step 5: one style for every back link. */
		back?: { href: string; label: string };
		heading?: Snippet; // in place of the title (a floor picker)
		adornment?: Snippet;
		description?: string;
		details?: Snippet;
		tabs?: Snippet;
		actions?: Snippet; // right of the tabs; may wrap under them on a narrow window
		children?: Snippet; // the row under the title: inner tabs, filters
		/** false for a page that fills the window and scrolls inside itself (a chat): the header just sits on top. */
		sticky?: boolean;
	}
	let { title, back, heading, adornment, description, details, tabs, actions, children, sticky = true }: Props = $props();

	let height = $state(0);
	$effect(() => {
		document.documentElement.style.setProperty('--page-header', `${height}px`);
		return () => document.documentElement.style.removeProperty('--page-header');
	});
</script>

<header class={['z-20 -mx-4 -mt-2 mb-3 bg-background/85 px-4 py-2 backdrop-blur md:-mx-6 md:px-6', sticky && 'sticky top-[var(--app-top,0px)]']} bind:clientHeight={height}>
	{#if back}<a href={back.href} class="mb-1 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft class="size-3.5" />{back.label}</a>{/if}
	<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
		<div class="flex max-w-full min-w-0 items-center gap-4">
			{#if heading}{@render heading()}{:else}
				<div class="flex shrink-0 items-center gap-1.5">
					<h1 class="brand-text-gradient text-xl font-semibold">{title}</h1>
					{#if adornment}{@render adornment()}{/if}
				</div>
			{/if}
			{#if tabs}<div class="min-w-0 overflow-x-auto overflow-y-hidden [scrollbar-width:none]">{@render tabs()}</div>{/if}
		</div>
		{#if actions}<div class="ml-auto flex flex-wrap items-center gap-2">{@render actions()}</div>{/if}
	</div>
	{#if details}<div class="mt-0.5 text-xs text-muted-foreground">{@render details()}</div>
	{:else if description}<p class="mt-0.5 text-xs text-muted-foreground">{description}</p>{/if}
	{#if children}<div class="mt-2">{@render children()}</div>{/if}
</header>
