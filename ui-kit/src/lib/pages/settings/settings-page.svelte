<script lang="ts">
	// The Settings page's shell, the same in every Hiro app: the page header with the top tabs, a row of inner tabs for
	// a group (Users & Roles, AI...), and the open tab's content. The tabs and who gets them come from the app's menu
	// (menu.ts, via pageTabs), so the menu and the page always agree. The address names the inner tab (?tab=users); a
	// group's tab opens the inner tab it showed last, else its first. The app gives only what is in each tab:
	//
	//   <SettingsPage content={{ hiroleague: hl, users, roles }} />   (each a snippet; see `content`)
	import type { Snippet } from 'svelte';
	import * as Tabs from '$kit/components/ui/tabs/index.js';
	import { firstLeaf, leavesOf, pageTabs, topOf } from '$kit/components/menu';
	import { UrlTab } from '$kit/state/url-tab.svelte';
	import { who } from '$kit/state/who.svelte';
	import PageHeader from '$kit/ui/page-header.svelte';

	let {
		content,
		title = 'Settings'
	}: {
		/** The content of each tab, by tab id (the menu's `value`). A snippet is told which tab is open (one snippet can
		 * serve several tabs) and gets a way to open another one. A tab the user may not see is never drawn. */
		content: Record<string, Snippet<[tab: string, select: (tab: string) => void]>>;
		title?: string;
	} = $props();

	// Only the tabs the user's role has (the layout already knows who this is).
	const groups = pageTabs(who.me, '/settings');
	const leaves = leavesOf(groups);
	const tab = new UrlTab('settings.tab', leaves, leaves[0] ?? '');
	const top = $derived(topOf(groups, tab.current));
	const body = $derived(content[tab.current]);

	let last = $state<Record<string, string>>({}); // the inner tab each group showed last
	$effect(() => {
		if (top?.subs) last[top.value] = tab.current;
	});
	const open = (value: string) => {
		const t = groups.find((x) => x.value === value);
		if (t) tab.current = last[value] ?? firstLeaf(t);
	};
	const select = (value: string) => (tab.current = value);
</script>

<PageHeader {title}>
	{#snippet tabs()}
		<Tabs.Root value={top?.value ?? ''} onValueChange={open}>
			<Tabs.List>
				{#each groups as t (t.value)}<Tabs.Trigger value={t.value}>{t.title}</Tabs.Trigger>{/each}
			</Tabs.List>
		</Tabs.Root>
	{/snippet}
	{#if top?.subs}
		<Tabs.Root bind:value={tab.current}>
			<Tabs.List variant="line" class="max-w-full justify-start overflow-x-auto overflow-y-hidden [scrollbar-width:none]">
				{#each top.subs as s (s.value)}<Tabs.Trigger value={s.value}><s.icon />{s.title}</Tabs.Trigger>{/each}
			</Tabs.List>
		</Tabs.Root>
	{/if}
</PageHeader>

<div class="grid gap-6">
	{@render body?.(tab.current, select)}
</div>
