<script lang="ts">
	// Logs: what the app did and what went wrong, from the files in DATA_DIR/logs. New lines appear as the web app
	// writes them. With an LLM requests tab (`LOGS.llm` in the app's logs.ts): every question sent to an LLM, as sent
	// and as answered.
	import { LOGS } from '$hiro-app/logs';
	import * as Tabs from '$kit/components/ui/tabs/index.js';
	import { UrlTab } from '$kit/state/url-tab.svelte';
	import PageHeader from '$kit/ui/page-header.svelte';
	import ResourceView from '$kit/ui/resource-view.svelte';
	import StickyBar from '$kit/ui/sticky-bar.svelte';
	import LlmRequests from './llm/llm-requests.svelte';
	import LogFiles from './log-files.svelte';
	import LogList from './log-list.svelte';
	import LogSummary from './log-summary.svelte';
	import LogToolbar from './log-toolbar.svelte';
	import { LogsPage } from './logs-state.svelte';

	const pg = new LogsPage();
	const tab = new UrlTab('logs.tab', ['app', 'llm'] as const, 'app');
</script>

{#snippet appLog()}
	<div class="grid grid-cols-[minmax(0,1fr)] gap-3">
		<LogSummary {pg} />
		<StickyBar><LogToolbar {pg} /></StickyBar>
		<ResourceView resource={pg.loaded} quiet errorTitle="Could not load the logs">
			{#snippet children(data)}
				{#each data.unreadable ?? [] as why (why)}<p class="text-sm text-warning">Not shown: {why}</p>{/each}
				{#if data.more}
					<p class="text-xs text-muted-foreground">Only the newest {data.lines.length} lines are shown: pick a shorter span, or Problems.</p>
				{/if}
				<LogList {pg} />
			{/snippet}
		</ResourceView>
		<LogFiles />
	</div>
{/snippet}

{#snippet newLines()}
	<span class="text-xs text-muted-foreground">New lines appear as they're written</span>
{/snippet}

{#if LOGS.llm}
	<Tabs.Root bind:value={tab.current}>
		<PageHeader title="Logs">
			{#snippet tabs()}
				<Tabs.List>
					<Tabs.Trigger value="app">App log</Tabs.Trigger>
					<Tabs.Trigger value="llm">LLM requests</Tabs.Trigger>
				</Tabs.List>
			{/snippet}
			{#snippet actions()}{@render newLines()}{/snippet}
		</PageHeader>
		<Tabs.Content value="llm" class="grid gap-2 pt-2">
			<!-- Phase 7b: what the requests add up to is counted by HiroLeague now (LLM usage moved there) -->
			<p class="text-xs text-muted-foreground">
				What these add up to, with Hiro's own AI use, is in HiroLeague's admin: <span class="font-medium text-foreground">Logs → AI usage</span>.
			</p>
			<LlmRequests />
		</Tabs.Content>
		<Tabs.Content value="app" class="pt-2">{@render appLog()}</Tabs.Content>
	</Tabs.Root>
{:else}
	<PageHeader title="Logs">
		{#snippet actions()}{@render newLines()}{/snippet}
	</PageHeader>
	<div class="pt-2">{@render appLog()}</div>
{/if}
