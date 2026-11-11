<script lang="ts">
	// The one dialog that `ask()` (confirm.svelte.ts) shows. Mounted once, in the layout. It sits a layer above
	// the other dialogs and side panels: mounted first, it comes first in the page, so on the same layer an open
	// panel (an editor asking "Discard your changes?") would cover it.
	import * as AlertDialog from '$kit/components/ui/alert-dialog/index.js';
	import { buttonVariants } from '$kit/components/ui/button/index.js';
	import { asking } from './confirm.svelte';

	const q = $derived(asking.question);
</script>

<AlertDialog.Root open={!!q} onOpenChange={(open) => !open && asking.answer(false)}>
	<AlertDialog.Content class="z-60" overlayClass="z-60">
		{#if q}
			<AlertDialog.Header>
				<AlertDialog.Title>{q.title}</AlertDialog.Title>
				{#if q.description}<AlertDialog.Description>{q.description}</AlertDialog.Description>{/if}
			</AlertDialog.Header>
			<AlertDialog.Footer>
				<AlertDialog.Cancel onclick={() => asking.answer(false)}>Cancel</AlertDialog.Cancel>
				<AlertDialog.Action class={q.danger ? buttonVariants({ variant: 'destructive' }) : undefined} onclick={() => asking.answer(true)}>{q.action ?? 'Continue'}</AlertDialog.Action>
			</AlertDialog.Footer>
		{/if}
	</AlertDialog.Content>
</AlertDialog.Root>
