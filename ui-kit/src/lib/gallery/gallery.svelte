<script lang="ts">
	// The UI kit's gallery: every shared piece, the Theme designer and the standard pages, with sample words only, so
	// it needs no backend. It is the kit's own home page and, as `Gallery`, a page in the HiroLeague admin (/ui-kit)
	// that shows the kit as that admin has it. It depends on an app only through what every app provides ($hiro-app).
	import { mode, toggleMode } from 'mode-watcher';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Tabs from '$kit/components/ui/tabs/index.js';
	import { Moon, Sun } from '@lucide/svelte';
	import Pieces from './pieces.svelte';
	import StandardPages from './standard-pages.svelte';
	import ThemeDesigner from './theme-designer.svelte';
	import { UrlTab } from '$kit/state/url-tab.svelte';

	// The open tab is in the address (?tab=theme), so Settings pages can link straight to the Theme designer.
	const tabs = new UrlTab('gallery.tab', ['pieces', 'theme', 'pages'] as const, 'pieces');
	const tab = $derived(tabs.current);
</script>

<div class="max-w-5xl">
	<Tabs.Root bind:value={tabs.current}>
		<div class="mb-4 flex flex-wrap items-center justify-between gap-2">
			<Tabs.List>
				<Tabs.Trigger value="pieces">Pieces</Tabs.Trigger>
				<Tabs.Trigger value="theme">Theme</Tabs.Trigger>
				<Tabs.Trigger value="pages">Standard pages</Tabs.Trigger>
			</Tabs.List>
			<Button variant="outline" size="sm" onclick={toggleMode}>
				{#if mode.current === 'dark'}<Sun /> Light mode{:else}<Moon /> Dark mode{/if}
			</Button>
		</div>
		<Tabs.Content value="pieces"><Pieces /></Tabs.Content>
		<Tabs.Content value="pages"><StandardPages /></Tabs.Content>
	</Tabs.Root>
	<!-- always mounted: its edits preview on every tab, and apply while the page is open -->
	<div class={tab === 'theme' ? '' : 'hidden'}><ThemeDesigner /></div>
</div>
