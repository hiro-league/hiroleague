<script lang="ts">
	// A table cell with a small round picture (or a grey disc when there is none) and a name that is cut short with an
	// ellipsis.
	// UI kit, step 7b: the picture is shadcn-svelte's Avatar; the grey disc is its empty fallback.
	import * as Avatar from '$kit/components/ui/avatar/index.js';

	let { photo, name }: { photo: string | null; name: string } = $props();
</script>

<td class="max-w-[220px] align-middle">
	<div class="flex min-w-0 items-center gap-2">
		<Avatar.Root class="size-8">
			{#if photo}<Avatar.Image src={photo} alt="" class="object-cover" />{/if}
			<Avatar.Fallback class="bg-muted-foreground/20" aria-hidden="true" />
		</Avatar.Root>
		<span class="min-w-0 truncate">{name}</span>
	</div>
</td>
