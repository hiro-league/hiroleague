<script lang="ts">
	// First tab in the retrieval trace dialog — the answer (a placeholder when the trace was opened from a node with
	// no answer), and above it the ideal answer when the caller gave one (an eval's gold answer; '' shows a placeholder).
	let { answer = '', ideal }: { answer?: string; ideal?: string } = $props();
</script>

<div class="grid gap-4 text-sm leading-6">
	{#if ideal !== undefined}
		<div class="flex flex-wrap items-start gap-3">
			<span class="min-w-[88px] shrink-0 pt-0.5 text-xs font-medium text-muted-foreground">Gold answer</span>
			{#if ideal}
				<span class="min-w-0 flex-1 whitespace-pre-wrap text-foreground">{ideal}</span>
			{:else}
				<span class="flex-1 italic text-muted-foreground">— (no gold answer)</span>
			{/if}
		</div>
	{/if}
	<div class="flex flex-wrap items-start gap-3">
		<span class="min-w-[88px] shrink-0 pt-0.5 text-xs font-medium text-muted-foreground">Answer</span>
		{#if answer}
			<span class="min-w-0 flex-1 whitespace-pre-wrap text-foreground">{answer}</span>
		{:else}
			<span class="flex-1 italic text-muted-foreground">— (no answer)</span>
		{/if}
	</div>
</div>
