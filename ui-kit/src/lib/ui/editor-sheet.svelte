<script lang="ts">
	// The side panel that edits one thing (a stream, a calculated copy): its title, a middle that
	// scrolls, what went wrong, and Delete, Cancel and Save at the bottom, which stay put. Delete asks
	// first (in-app, not the browser's dialog). With `dirty` (unsaved changes), closing it or leaving
	// the page asks first too.
	import type { Snippet } from 'svelte';
	import * as Sheet from '$kit/components/ui/sheet/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import { Trash2, TriangleAlert } from '@lucide/svelte';
	import ConfirmDelete from './confirm-delete.svelte';
	import { ask } from './confirm.svelte';
	import { guardUnsaved } from './unsaved.svelte';

	interface Props {
		open: boolean;
		title: string;
		description?: Snippet;
		/** Instead of the title and description, e.g. with a picture. */
		header?: Snippet;
		wide?: boolean;
		/** Wider still: a panel with tabs side by side (the stream panels). */
		wider?: boolean;
		/** The widest: a panel with a wide table (the Wake word's log). */
		widest?: boolean;
		children: Snippet;
		error?: string;
		saveLabel: string;
		canSave: boolean;
		/** Changes not saved yet. */
		dirty?: boolean;
		onsave: () => void;
		/** A saved one can be deleted: what the question says, and the delete itself. */
		remove?: { title: string; description: string; onconfirm: () => Promise<void> | void };
	}
	let { open = $bindable(), title, description, header, wide = false, wider = false, widest = false, children, error = '', saveLabel, canSave, dirty = false, onsave, remove }: Props = $props();
	let confirming = $state(false);
	$effect(() => {
		if (open) confirming = false;
	});

	guardUnsaved(() => open && dirty);
	/** Cancel, Escape or a click beside the panel: with changes, only once they are discarded. */
	async function setOpen(v: boolean) {
		if (v || !dirty || (await ask({ title: 'Discard your changes?', action: 'Discard', danger: true }))) open = v;
	}
</script>

<Sheet.Root bind:open={() => open, (v) => void setOpen(v)}>
	<Sheet.Content class={['w-full gap-0', widest ? 'data-[side=right]:sm:max-w-5xl' : wider ? 'data-[side=right]:sm:max-w-3xl' : wide ? 'data-[side=right]:sm:max-w-2xl' : 'data-[side=right]:sm:max-w-lg']}>
		<Sheet.Header>
			{#if header}
				{@render header()}
			{:else}
				<Sheet.Title>{title}</Sheet.Title>
				{#if description}<Sheet.Description class="flex items-center gap-1.5">{@render description()}</Sheet.Description>{/if}
			{/if}
		</Sheet.Header>
		<div class="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] content-start gap-6 overflow-y-auto px-4 pb-4 text-sm">
			{@render children()}
			{#if error}<p class="flex gap-2 text-xs text-destructive"><TriangleAlert class="size-4 shrink-0" />{error}</p>{/if}
		</div>
		<Sheet.Footer class="flex-row items-center gap-2 border-t">
			{#if remove}
				<Button variant="ghost" class="mr-auto text-destructive" onclick={() => (confirming = true)}><Trash2 /> Delete</Button>
			{/if}
			<Button variant="outline" class={remove ? '' : 'ml-auto'} onclick={() => setOpen(false)}>Cancel</Button>
			<Button onclick={onsave} disabled={!canSave}>{saveLabel}</Button>
		</Sheet.Footer>
	</Sheet.Content>
</Sheet.Root>

{#if remove}
	<ConfirmDelete bind:open={confirming} title={remove.title} description={remove.description} onconfirm={remove.onconfirm} />
{/if}
