<script lang="ts" generics="T">
	// A Resource's data with its states, the same on every page: "Loading…" before the first answer, what went wrong
	// (with Try again) when there is nothing to show, the empty state when the data holds nothing, and the data itself.
	// While it reloads or after a failed reload the data stays, with a quiet line above it (updating / out of date).
	// UI kit, step 5: pages wrote these four states by hand, each a little differently.
	//
	//   <ResourceView resource={list} empty={(d) => d.items.length === 0} emptyMessage="No cameras yet.">
	//     {#snippet children(d)}…{/snippet}
	//   </ResourceView>
	import type { Snippet } from 'svelte';
	import { RefreshCw } from '@lucide/svelte';
	import { Button } from '$kit/components/ui/button/index.js';
	import EmptyState from './empty-state.svelte';
	import Loading from './loading.svelte';
	import Notice from './notice.svelte';

	/** What it reads from a Resource (or anything shaped like one). */
	type Source = { data: T | null; error: string; loading: boolean; reload?: () => unknown };

	interface Props {
		resource: Source;
		children: Snippet<[T]>;
		/** The data holds nothing (show the empty state instead). */
		empty?: (data: T) => boolean;
		emptyMessage?: string;
		emptyHint?: string;
		/** The empty state's own content (an icon, an Add button), in place of the words. */
		emptyState?: Snippet;
		loadingLabel?: string;
		/** The title of the error box ("Could not load the cameras"). */
		errorTitle?: string;
		/** Hide the quiet "updating" line during reloads (a page that polls often). */
		quiet?: boolean;
	}
	let {
		resource,
		children,
		empty,
		emptyMessage = 'Nothing here yet.',
		emptyHint,
		emptyState,
		loadingLabel = 'Loading…',
		errorTitle = 'Could not load this',
		quiet = false
	}: Props = $props();

	const data = $derived(resource.data);
</script>

{#if data === null}
	{#if resource.error}
		<Notice title={errorTitle} message={resource.error}>
			{#snippet actions()}
				{#if resource.reload}<Button size="sm" variant="outline" onclick={() => void resource.reload?.()}><RefreshCw />Try again</Button>{/if}
			{/snippet}
		</Notice>
	{:else}
		<Loading label={loadingLabel} />
	{/if}
{:else}
	{#if resource.error}
		<p class="mb-2 text-xs text-warning" role="status">Out of date: {resource.error}</p>
	{:else if resource.loading && !quiet}
		<p class="mb-2 text-xs text-muted-foreground" role="status">Updating…</p>
	{/if}
	{#if empty?.(data)}
		{#if emptyState}{@render emptyState()}{:else}<EmptyState message={emptyMessage} hint={emptyHint} />{/if}
	{:else}
		{@render children(data)}
	{/if}
{/if}
