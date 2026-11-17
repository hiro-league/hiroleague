<script lang="ts">
	// The memories table: a graph partition's long-term memories (Graphiti facts) with their filters and sort (kept in
	// the address, `mem_*`), the source turns behind a fact, and Clear memories / Clear group. It makes its own
	// controller and loads once mounted; every call goes through `source`. A page with tabs keeps it mounted and passes
	// `hidden` while another tab shows, so its rows and filters stay without a reload; the tab button takes its ids from
	// `MEMORIES_A11Y` (`./shared/memories-a11y`).
	// UI kit: from the HiroLeague admin's Memories page.
	import { onMount } from 'svelte';
	import { Eye, MessagesSquare } from '@lucide/svelte';
	import TableShell from '$kit/ui/table-shell.svelte';
	import SortHead from '$kit/ui/sort-head.svelte';
	import AvatarNameCell from '$kit/ui/avatar-name-cell.svelte';
	import { Badge } from '$kit/components/ui/badge/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import Loading from '$kit/ui/loading.svelte';
	import Notice from '$kit/ui/notice.svelte';
	import EmptyState from '$kit/ui/empty-state.svelte';
	import type { MemorySource } from '$kit/memory/source';
	import MemoriesEntitiesCell from './memories-entities-cell.svelte';
	import MemoriesToolbar from './memories-toolbar.svelte';
	import MemoriesDialogs from './memories-dialogs.svelte';
	import { createMemoriesController } from './state/memories-controller.svelte';
	import {
		memoryCharacter,
		memoryChunkIds,
		memoryCreatedRaw,
		memoryDateDisplay,
		memoryEntities,
		memoryGroupId,
		memoryId,
		memoryKind,
		memoryKindLabel,
		memoryPrimaryText,
		memoryStableKey,
		memoryValidity
	} from './shared/memory-pure';
	import { MEMORIES_A11Y } from './shared/memories-a11y';

	interface Props {
		/** Where the rows, groups, names and source turns come from (the app's own calls). */
		source: MemorySource;
		/** Hides the panel while the page shows another tab (the toolbar isn't drawn then). */
		hidden?: boolean;
	}

	let { source, hidden = false }: Props = $props();

	// A getter, so the controller always calls the current source.
	const ctl = createMemoriesController({
		get source() {
			return source;
		}
	});

	onMount(() => {
		ctl.mount();
	});

	const characterOptions = $derived(
		ctl.charactersForFilterDropdown.map((c) => ({ value: c.id, label: c.name || c.id }))
	);
</script>

<div
	id={MEMORIES_A11Y.memoriesPanel}
	class="flex min-w-0 flex-col gap-4"
	role="tabpanel"
	aria-labelledby={MEMORIES_A11Y.memoriesTab}
	{hidden}
>
	{#if ctl.memoriesError}
		<Notice message={ctl.memoriesError} />
	{/if}

	<div class="memories-panel">
		{#if ctl.memoriesLoading}
			<Loading label="Loading memories…" class="m-0" />
		{:else if ctl.memoryEnabled === false}
			<EmptyState
				message="Long-term memory is disabled or not configured for this workspace (settings or missing models)."
			/>
		{:else if ctl.memoriesError}
			<!-- Error banner above -->
		{:else}
			{#if !hidden}
				<MemoriesToolbar
					filters={ctl.filters}
					setFilter={ctl.setFilter}
					groupsForMemoryFilterDropdown={ctl.memoryGroupsForFilterDropdown}
					{characterOptions}
					sourcesForMemoryFilterDropdown={ctl.sourcesForMemoryFilterDropdown}
					canClearMemories={ctl.canClearMemories}
					clearableMemoryCount={ctl.clearableMemoryCount}
					memoryActionBusy={ctl.memoryActionBusy}
					memoriesLoading={ctl.memoriesLoading}
					onRequestClearMemories={ctl.requestClearMemoriesConfirm}
					onRequestClearGroup={ctl.requestClearGroupConfirm}
					onRefreshMemories={() => void ctl.refreshMemories()}
				/>
			{/if}

			{#if ctl.sortedMemoriesRows.length === 0}
				<EmptyState message="No memories in the store for the default user yet." />
			{:else if ctl.visibleMemoriesRows.length === 0}
				<EmptyState message="No memories match the current filters." />
			{:else}
				<div class="memories-table-container">
					<TableShell density="dense" stickyHead class="memories-table-wrap">
						<thead>
							<tr>
								<SortHead key="kind" sorter={ctl.sort}>Kind</SortHead>
								<SortHead key="created" sorter={ctl.sort}>Created</SortHead>
								<SortHead key="validity" sorter={ctl.sort}>Validity</SortHead>
								<SortHead key="character" sorter={ctl.sort}>Character</SortHead>
								<SortHead key="memory" sorter={ctl.sort}>Memory</SortHead>
								<SortHead key="entities" sorter={ctl.sort}>Entities</SortHead>
								<SortHead key="group" sorter={ctl.sort}>Group</SortHead>
								<SortHead key="origin" sorter={ctl.sort}>Origin</SortHead>
								<SortHead key="id" sorter={ctl.sort}>Id</SortHead>
								<SortHead key="id" sorter={ctl.sort} sortable={false}>Payload</SortHead>
							</tr>
						</thead>
						<tbody>
							{#each ctl.visibleMemoriesRows as row, idx (memoryStableKey(row, idx))}
								{@const kind = memoryKind(row)}
								{@const created = memoryDateDisplay(memoryCreatedRaw(row))}
								{@const validity = memoryValidity(row)}
								{@const invalidDisp = memoryDateDisplay(validity.invalidAt)}
								{@const entities = memoryEntities(row)}
								{@const groupLabel = ctl.memoryGroupLabelById.get(memoryGroupId(row)) || memoryGroupId(row)}
								{@const chunkCount = memoryChunkIds(row).length}
								{@const memCharacter = memoryCharacter(row, ctl.characterMap, ctl.channelById)}
								<tr>
									<td>
										{#if kind}
											<Badge variant={kind === 'relation' ? 'secondary' : 'outline'}>
												{memoryKindLabel(row)}
											</Badge>
										{:else}
											—
										{/if}
									</td>
									<td class="memories-date-cell" title={created.title}>
										<span>{created.date}</span>
										<span>{created.time}</span>
									</td>
									<td>
										{#if validity.expired}
											<Badge
												variant="warning"
												title={`Stopped being true on ${invalidDisp.title || invalidDisp.date}`}
											>
												Expired{invalidDisp.date !== '—' ? ` ${invalidDisp.date}` : ''}
											</Badge>
										{:else}
											<Badge variant="success">Current</Badge>
										{/if}
									</td>
									<AvatarNameCell photo={memCharacter.photo} name={memCharacter.name} />
									<td class="memories-text-cell">{memoryPrimaryText(row)}</td>
									<MemoriesEntitiesCell {entities} />
									<td class="memories-group-cell" title={groupLabel}>{groupLabel || '—'}</td>
									<td class="memories-origin-cell">
										{#if chunkCount > 0}
											<Button
												type="button"
												variant="ghost"
												size="sm"
												class="h-7 gap-1 px-2 text-xs shadow-none"
												title="View the conversation turn(s) this fact came from"
												onclick={() => void ctl.showMemoryProvenance(row)}
											>
												<MessagesSquare size={14} aria-hidden="true" />
												{chunkCount}
												{chunkCount === 1 ? 'turn' : 'turns'}
											</Button>
										{:else}
											—
										{/if}
									</td>
									<td class="font-mono memories-id-cell">{memoryId(row) || '—'}</td>
									<td class="memories-payload-cell">
										<Button
											type="button"
											variant="ghost"
											size="sm"
											class="h-7 gap-1 px-2 text-xs shadow-none"
											onclick={() => ctl.showMemoryJsonRow(row)}
										>
											<Eye size={14} aria-hidden="true" />
											View JSON
										</Button>
									</td>
								</tr>
							{/each}
						</tbody>
					</TableShell>
				</div>
			{/if}
		{/if}
	</div>
</div>

<MemoriesDialogs
	memoryJsonRow={ctl.memoryJsonRow}
	memoryProvenanceRow={ctl.memoryProvenanceRow}
	memoryProvenanceChunks={ctl.memoryProvenanceChunks}
	memoryProvenanceLoading={ctl.memoryProvenanceLoading}
	memoryProvenanceError={ctl.memoryProvenanceError}
	clearMemoriesConfirmOpen={ctl.clearMemoriesConfirmOpen}
	clearGroupConfirmOpen={ctl.clearGroupConfirmOpen}
	clearableMemoryCount={ctl.clearableMemoryCount}
	selectedGroupLabel={ctl.selectedGroupLabel}
	memoryActionBusy={ctl.memoryActionBusy}
	onCloseMemoryJson={ctl.closeMemoryJsonDialog}
	onCloseProvenance={ctl.closeMemoryProvenance}
	onCloseClearMemories={ctl.closeClearMemoriesDialog}
	onConfirmClearMemories={() => void ctl.confirmClearMemories()}
	onCloseClearGroup={ctl.closeClearGroupDialog}
	onConfirmClearGroup={() => void ctl.confirmClearGroup()}
/>

<style>
	.memories-panel {
		display: flex;
		flex-direction: column;
		gap: 12px;
		min-height: 120px;
	}

	.memories-table-container :global(table) {
		white-space: normal;
		min-width: 1180px;
	}

	.memories-date-cell {
		min-width: 86px;
		white-space: nowrap;
		color: var(--muted-foreground, #64748b);
	}

	.memories-date-cell span {
		display: block;
		line-height: 1.35;
	}

	.memories-text-cell {
		max-width: min(480px, 40vw);
		white-space: normal;
		word-break: break-word;
	}

	.memories-id-cell {
		max-width: 140px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.memories-group-cell {
		max-width: 180px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--muted-foreground, #64748b);
	}

	.memories-origin-cell {
		min-width: 90px;
		white-space: nowrap;
	}

	.memories-payload-cell {
		vertical-align: top;
		min-width: 100px;
	}
</style>
