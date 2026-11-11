<script lang="ts">
	// Asks before something is deleted for good (an in-app dialog, not the browser's). The Delete button
	// waits for `onconfirm`; the dialog closes when it is done.
	import * as AlertDialog from '$kit/components/ui/alert-dialog/index.js';
	import { buttonVariants } from '$kit/components/ui/button/index.js';

	let {
		open = $bindable(false),
		title,
		description,
		action = 'Delete',
		onconfirm
	}: { open?: boolean; title: string; description: string; action?: string; onconfirm: () => Promise<void> | void } = $props();
	let busy = $state(false);

	async function confirm() {
		busy = true;
		try {
			await onconfirm();
		} finally {
			busy = false;
			open = false;
		}
	}
</script>

<AlertDialog.Root bind:open>
	<AlertDialog.Content>
		<AlertDialog.Header>
			<AlertDialog.Title>{title}</AlertDialog.Title>
			<AlertDialog.Description>{description}</AlertDialog.Description>
		</AlertDialog.Header>
		<AlertDialog.Footer>
			<AlertDialog.Cancel disabled={busy}>Cancel</AlertDialog.Cancel>
			<AlertDialog.Action class={buttonVariants({ variant: 'destructive' })} disabled={busy} onclick={confirm}>{action}</AlertDialog.Action>
		</AlertDialog.Footer>
	</AlertDialog.Content>
</AlertDialog.Root>
