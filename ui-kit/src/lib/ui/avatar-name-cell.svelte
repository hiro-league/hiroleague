<script lang="ts">
	// A table cell with a small round picture (or a grey disc when there is none) and a name that is cut short with an
	// ellipsis. UI kit, step 7: from the HiroLeague admin's ledger tables.
	let { photo, name }: { photo: string | null; name: string } = $props();
</script>

<td class="max-w-[220px] align-middle">
	<div class="flex min-w-0 items-center gap-2">
		{#if photo}
			<img class="block size-8 shrink-0 rounded-full object-cover shadow-[inset_0_0_0_1px_rgb(0_0_0/0.1)]" src={photo} alt="" width="32" height="32" />
		{:else}
			<div class="block size-8 shrink-0 rounded-full bg-muted-foreground/20" aria-hidden="true"></div>
		{/if}
		<span class="min-w-0 truncate">{name}</span>
	</div>
</td>
