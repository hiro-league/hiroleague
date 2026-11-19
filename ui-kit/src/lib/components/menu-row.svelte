<script lang="ts" module>
	import type { Component } from 'svelte';

	/** One shortcut on a menu row: a link to one of the row's tabs. */
	export type MenuShortcut = { href: string; label: string; tip: string; icon: Component; on?: boolean };

	/** For the row's button: it keeps its hover colour while the pointer is on the shortcuts over it. */
	export const MENU_ROW_HOVER = 'group-hover/menu-row:bg-sidebar-accent group-hover/menu-row:text-sidebar-accent-foreground';

	/** For a titled group's list of rows: a little in from its heading, so the rows read as under it (not when the menu
	 * is folded to icons, where there is no heading). An app's own part of the menu uses it too. */
	export const MENU_INDENT = 'pl-2 group-data-[collapsible=icon]:pl-0';
</script>

<script lang="ts">
	// A side-menu row with shortcuts: the row's button (children), and its tabs as small icons at the row's end,
	// shown only while the row is hovered or one of them has focus, over the end of the name (it fades under them).
	// The kit's pages use it (app-sidebar), and so does an app's own part of the menu (Code reports' projects).
	// On a touch screen they don't show: the page's own tabs are a tap away.
	import type { Snippet } from 'svelte';
	import * as Tooltip from '$kit/components/ui/tooltip/index.js';

	interface Props {
		shortcuts: MenuShortcut[];
		/** How far in from the row's end they sit, in pixels (room for a fold button there). */
		right?: number;
		children: Snippet;
	}
	let { shortcuts, right = 4, children }: Props = $props();
</script>

<div class="group/menu-row relative">
	{@render children()}
	{#if shortcuts.length}
		<div
			class="absolute top-1/2 hidden -translate-y-1/2 gap-0.5 rounded-md bg-sidebar-accent before:pointer-events-none before:absolute before:inset-y-0 before:right-full before:w-4 before:bg-linear-to-l before:from-sidebar-accent group-focus-within/menu-row:flex group-hover/menu-row:flex group-data-[collapsible=icon]:hidden! [@media(hover:none)]:hidden!"
			style="right: {right}px"
		>
			{#each shortcuts as s (s.href)}
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}
							<a
								{...props}
								type={undefined}
								href={s.href}
								aria-label={s.label}
								aria-current={s.on ? 'page' : undefined}
								class={[
									'flex size-6 items-center justify-center rounded-md [&_svg]:size-3.5',
									s.on ? 'bg-background text-foreground shadow-sm ring-1 ring-sidebar-border' : 'text-sidebar-foreground/60 hover:bg-background/70 hover:text-sidebar-accent-foreground'
								]}><s.icon /></a
							>
						{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content side="bottom">{s.tip}</Tooltip.Content>
				</Tooltip.Root>
			{/each}
		</div>
	{/if}
</div>
