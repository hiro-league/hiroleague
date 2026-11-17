<script lang="ts" module>
	import type { Component } from 'svelte';

	/** One tab of a page. With `href` it is a real link (it can be opened in a new tab or copied); else picking it
	 * calls `onchange`. `kind` is only read for its meaning by the app that wrote the list. */
	export type PageTab<T extends string = string> = {
		id: T;
		label: string;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any -- any icon component (lucide's, or an app's own)
		icon?: Component<any>;
		href?: string;
		kind?: 'pane' | 'route';
		disabled?: boolean;
		count?: number | string;
		title?: string;
		ariaLabel?: string;
		htmlId?: string;
		ariaControls?: string;
	};
</script>

<script lang="ts" generics="T extends string">
	// A page's tabs from a list, in the page header: the pill strip (the page's main tabs) or the underlined strip
	// (tabs inside a tab). It adds what a list of tabs needs: a tab that is a link, a count beside a name, and a place
	// after the tabs for one more of the page's own (an open record's tab).
	// UI kit, step 7d: built on shadcn-svelte's Tabs (its list and triggers: the arrow keys move between tabs, Enter
	// or a click picks one); a tab with `href` is still a link. Tabs size to their words, not to equal widths.
	import type { Snippet } from 'svelte';
	import * as Tabs from '$kit/components/ui/tabs/index.js';
	import { cn } from '$kit/utils';

	interface Props {
		tabs: readonly PageTab<T>[];
		value: T;
		onchange?: (id: T) => void;
		label: string; // what the tabs choose, for screen readers
		variant?: 'default' | 'line';
		class?: string;
		extra?: Snippet;
	}
	let { tabs, value, onchange, label, variant = 'default', class: className, extra }: Props = $props();

	// dark: a blue tint on the picked pill, since the light pill's raised look is lost there
	const TAB = cn(
		'flex-none px-2',
		variant === 'default' && 'dark:data-active:border-primary/60 dark:data-active:bg-primary/30'
	);
</script>

<Tabs.Root value={value} onValueChange={(v) => v !== value && onchange?.(v as T)} activationMode="manual" class="w-fit max-w-full gap-0">
	<Tabs.List {variant} aria-label={label} class={cn('max-w-full', className)}>
		{#each tabs as t (t.id)}
			<Tabs.Trigger value={t.id} disabled={t.disabled} id={t.htmlId} aria-label={t.ariaLabel} aria-controls={t.ariaControls} title={t.title} class={TAB}>
				{#snippet child({ props })}
					{#if t.href}
						<a {...props} href={t.disabled ? undefined : t.href}
							>{#if t.icon}<t.icon />{/if}{t.label}{#if t.count !== undefined}<span class="text-xs text-muted-foreground tabular-nums">({t.count})</span>{/if}</a
						>
					{:else}
						<button {...props}
							>{#if t.icon}<t.icon />{/if}{t.label}{#if t.count !== undefined}<span class="text-xs text-muted-foreground tabular-nums">({t.count})</span>{/if}</button
						>
					{/if}
				{/snippet}
			</Tabs.Trigger>
		{/each}
		{#if extra}{@render extra()}{/if}
	</Tabs.List>
</Tabs.Root>
