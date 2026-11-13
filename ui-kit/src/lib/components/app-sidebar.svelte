<script lang="ts">
	// The menu in two levels (menu.ts). A group's name folds it away (remembered in this browser); a folded
	// group still shows the page you are on. A page's tabs are the icons on its row. A page's link always opens
	// its first tab, and neither it nor a tab icon changes the tab a page remembers. Collapsed to icons, a page
	// with tabs opens a small menu of them instead. Its edge resizes it (dragged) or collapses it (clicked). A tab
	// with sub-tabs (Settings' groups) opens its first one; its tooltip names them, the small menu lists them.
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import * as Sidebar from '$kit/components/ui/sidebar/index.js';
	import * as DropdownMenu from '$kit/components/ui/dropdown-menu/index.js';
	import * as Tooltip from '$kit/components/ui/tooltip/index.js';
	import { ChevronRight, LogOut, Moon, Sun } from '@lucide/svelte';
	import { mode, toggleMode } from 'mode-watcher';
	import { cn } from '$kit/utils';
	import { APP } from '$hiro-app/app'; // UI kit, step 1: the app's name, icon and words come from lib/app/app.ts, so this file is the same in every Hiro app.
	import { who } from '$kit/state/who.svelte';
	import { load, isRecord } from '$kit/state/persist';
	import { persisted } from '$kit/state/persisted.svelte';
	import { tabLink } from '$kit/state/url-tab.svelte';
	import { firstLeaf, menuFor, onPage, tabShown, tabsFit, type MenuPage, type MenuTab } from './menu';
	import SidebarResize from './sidebar-resize.svelte';
	import AppSwitcher from './app-switcher.svelte';

	interface Props {
		width: number; // the menu's width in pixels
		onwidth: (px: number) => void;
	}
	let { width, onwidth }: Props = $props();

	const sidebar = Sidebar.useSidebar();

	const menu = $derived(menuFor(who.me));
	const closed = persisted<Record<string, boolean>>('sidebar.closedGroups', {}, isRecord);
	const iconMenu = $derived(sidebar.state === 'collapsed' && !sidebar.isMobile);
	// A page's tab icons sit on its row when they fit beside its name at the menu's width; else on a line of their own.
	const canvas = typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d');
	const nameWidth = (name: string) => {
		if (!canvas) return name.length * 8;
		canvas.font = `500 14px ${getComputedStyle(document.body).fontFamily}`;
		return canvas.measureText(name).width;
	};

	const path = (p: MenuPage) => resolve(p.route as '/');
	// A page's link opens its first tab, whatever tab it showed last
	const href = (p: MenuPage) => (p.tabs?.length ? tabLink(path(p), firstLeaf(p.tabs[0])) : path(p));
	const tip = (t: MenuTab) => (t.subs && (t.subs.length > 1 || t.subs[0].title !== t.title) ? `${t.title}: ${t.subs.map((s) => s.title).join(', ')}` : t.title);
	const shownTab = (p: MenuPage) => tabShown(p, page.url.searchParams.get('tab'), p.pref ? load(p.pref, null) : null);
	const toggle = (id: string) => (closed.current = { ...closed.current, [id]: !closed.current[id] });
</script>

<Sidebar.Root collapsible="icon">
	<!-- The collapse button sits here, so pages start at the top of the window. Collapsed to icons, the
	     name makes way for it, and the app switcher goes under it. -->
	<Sidebar.Header>
		<Sidebar.Menu>
			<Sidebar.MenuItem class="flex items-center gap-1 group-data-[collapsible=icon]:flex-col">
				<!-- The name goes to the home page (someone without it is sent on to their first page). -->
				<Sidebar.MenuButton class="group-data-[collapsible=icon]:hidden">
					{#snippet child({ props })}
						<a href={resolve('/')} {...props}>
							<APP.icon />
							<span class="brand-text-gradient font-semibold">{APP.name}</span>
						</a>
					{/snippet}
				</Sidebar.MenuButton>
				<!-- Every app the person may open, to move between them (app-switcher.svelte) -->
				<AppSwitcher />
				<Sidebar.Trigger
					class="shrink-0 text-muted-foreground"
					title={sidebar.state === 'collapsed' ? 'Expand menu' : 'Collapse menu'}
				/>
			</Sidebar.MenuItem>
		</Sidebar.Menu>
	</Sidebar.Header>
	<!-- On a phone the menu is a sheet over the page: a link closes it. -->
	<Sidebar.Content class="gap-0" onclick={(e) => sidebar.isMobile && e.target instanceof Element && e.target.closest('a') && sidebar.setOpenMobile(false)}>
		{#each menu as g, i (g.id)}
			{@const open = !closed.current[g.id]}
			{#if iconMenu && i > 0}<Sidebar.Separator class="mx-3" />{/if}
			<Sidebar.Group class="py-1">
				<!-- Collapsed to icons, a group's name fades out and moves up over the page above it: it mustn't take that page's clicks. -->
				<Sidebar.GroupLabel>
					{#snippet child({ props })}
						<button {...props} type="button" class={cn(props.class as string, 'w-full uppercase tracking-wide hover:text-sidebar-foreground group-data-[collapsible=icon]:pointer-events-none')} aria-expanded={open} onclick={() => toggle(g.id)}>
							<span class="accent-text-gradient font-semibold">{g.title}</span>
							<ChevronRight class={['ml-auto transition-transform', open && 'rotate-90']} />
						</button>
					{/snippet}
				</Sidebar.GroupLabel>
				<Sidebar.Menu>
					{#each g.pages.filter((p) => open || iconMenu || onPage(p, page.route.id)) as p (p.route)}
						{@render pageItem(p)}
					{/each}
				</Sidebar.Menu>
			</Sidebar.Group>
		{/each}
	</Sidebar.Content>
	<Sidebar.Footer>
		<Sidebar.Menu>
			{#if who.me?.way === 'web'}
				<Sidebar.MenuItem>
					<Sidebar.MenuButton onclick={() => void who.signOut()} tooltipContent="Sign out {who.me.name}">
						<LogOut />
						<span class="truncate">Sign out · {who.me.name}</span>
					</Sidebar.MenuButton>
				</Sidebar.MenuItem>
			{/if}
			<Sidebar.MenuItem>
				{@const dark = mode.current === 'dark'}
				<Sidebar.MenuButton onclick={toggleMode} tooltipContent={dark ? 'Light mode' : 'Dark mode'}>
					{#if dark}<Sun />{:else}<Moon />{/if}
					<span>{dark ? 'Light mode' : 'Dark mode'}</span>
				</Sidebar.MenuButton>
			</Sidebar.MenuItem>
		</Sidebar.Menu>
	</Sidebar.Footer>
	<SidebarResize {width} {onwidth} />
</Sidebar.Root>

<!-- One page: its name, and its tabs as icons (on the row, or on a line under it when there are many). -->
{#snippet pageItem(p: MenuPage)}
	{@const active = onPage(p, page.route.id)}
	{@const tabs = p.tabs ?? []}
	{@const current = active ? shownTab(p) : null}
	{@const wrap = tabs.length > 0 && !tabsFit(width, nameWidth(p.title), tabs.length)}
	<Sidebar.MenuItem>
		{#if iconMenu && tabs.length > 1}
			<DropdownMenu.Root>
				<DropdownMenu.Trigger>
					{#snippet child({ props })}
						<Sidebar.MenuButton {...props} isActive={active} aria-label={p.title}>
							<p.icon />
							<span>{p.title}</span>
						</Sidebar.MenuButton>
					{/snippet}
				</DropdownMenu.Trigger>
				<DropdownMenu.Content side="right" align="start" class="w-48">
					<DropdownMenu.Item>
						{#snippet child({ props })}
							<a href={href(p)} {...props}><p.icon /><span class="font-medium">{p.title}</span></a>
						{/snippet}
					</DropdownMenu.Item>
					<DropdownMenu.Separator />
					{#each tabs as t (t.value)}
						{#if t.subs}
							<DropdownMenu.Label class={['flex items-center gap-2 text-xs font-normal text-muted-foreground [&_svg]:size-3.5', current === t.value && 'text-foreground']}
								><t.icon />{t.title}</DropdownMenu.Label
							>
							{#each t.subs as s (s.value)}
								<DropdownMenu.Item class="pl-6">
									{#snippet child({ props })}
										<a href={tabLink(path(p), s.value)} {...props}><s.icon />{s.title}</a>
									{/snippet}
								</DropdownMenu.Item>
							{/each}
						{:else}
							<DropdownMenu.Item class={[current === t.value && 'bg-accent text-accent-foreground']}>
								{#snippet child({ props })}
									<a href={tabLink(path(p), t.value)} {...props} aria-current={current === t.value ? 'page' : undefined}><t.icon />{t.title}</a>
								{/snippet}
							</DropdownMenu.Item>
						{/if}
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>
		{:else}
			<Sidebar.MenuButton isActive={active} tooltipContent={p.title} style={tabs.length && !wrap ? `padding-right: ${tabs.length * 26 + 4}px` : undefined}>
				{#snippet child({ props })}
					<a href={href(p)} {...props}>
						<p.icon />
						<span>{p.title}</span>
					</a>
				{/snippet}
			</Sidebar.MenuButton>
			{#if tabs.length}
				<div class={['flex gap-0.5 group-data-[collapsible=icon]:hidden', wrap ? 'flex-wrap pt-0.5 pb-1 pl-7' : 'absolute top-1 right-1']}>
					{#each tabs as t (t.value)}
						{@const on = current === t.value}
						<Tooltip.Root>
							<Tooltip.Trigger>
								{#snippet child({ props })}
									<a
										{...props}
										type={undefined}
										href={tabLink(path(p), firstLeaf(t))}
										aria-label="{p.title} › {t.title}"
										aria-current={on ? 'page' : undefined}
										class={[
											'flex size-6 items-center justify-center rounded-md [&_svg]:size-3.5',
											on ? 'bg-background text-foreground shadow-sm ring-1 ring-sidebar-border' : 'text-sidebar-foreground/55 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'
										]}><t.icon /></a
									>
								{/snippet}
							</Tooltip.Trigger>
							<Tooltip.Content side="bottom">{tip(t)}</Tooltip.Content>
						</Tooltip.Root>
					{/each}
				</div>
			{/if}
		{/if}
	</Sidebar.MenuItem>
{/snippet}
