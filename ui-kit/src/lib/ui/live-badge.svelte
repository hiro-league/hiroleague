<script lang="ts">
	// Whether the app is connected live to `to` (e.g. "Home Assistant": changes appear as they happen).
	// UI kit, step 1: what it is connected to is the caller's to say, so this file is the same in every Hiro app.
	import { formatTime } from '$kit/format/time';

	/** A live connection as the backend reports it: up since when, or down and why. */
	type LiveStatus = { connected: boolean; since: string | null; error: string | null };

	let { status, to }: { status: LiveStatus | null; to: string } = $props();

	const title = $derived(
		!status
			? `Checking the connection to ${to}…`
			: status.connected
				? `Connected live to ${to} since ${formatTime(status.since)}. Changes appear as they happen.`
				: `Not connected to ${to}: ${status.error ?? 'reconnecting'}. Retrying automatically.`
	);
</script>

<span class="inline-flex items-center gap-2 text-sm text-muted-foreground" {title}>
	<span class="relative flex size-2.5">
		{#if status?.connected}
			<span class="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60"></span>
			<span class="relative inline-flex size-2.5 rounded-full bg-success"></span>
		{:else}
			<span class="relative inline-flex size-2.5 rounded-full {status ? 'bg-warning' : 'bg-muted-foreground'}"></span>
		{/if}
	</span>
	{status?.connected ? 'Live' : status ? 'Reconnecting…' : '…'}
</span>
