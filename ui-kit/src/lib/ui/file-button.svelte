<script lang="ts">
	// A button that opens the file picker: the words are yours (Upload a photo, Import…), the files come back to
	// `onfiles`. The picker forgets them after, so the same file can be picked again.
	// UI kit, step 3: the apps hid a file input behind a label or a button by hand.
	import type { Snippet } from 'svelte';
	import { Button, type ButtonSize, type ButtonVariant } from '$kit/components/ui/button/index.js';

	interface Props {
		onfiles: (files: File[]) => void;
		accept?: string;
		multiple?: boolean;
		disabled?: boolean;
		variant?: ButtonVariant;
		size?: ButtonSize;
		class?: string;
		title?: string;
		children: Snippet;
	}
	let { onfiles, accept, multiple = false, disabled = false, variant = 'outline', size = 'sm', class: className, title, children }: Props = $props();
	let input = $state<HTMLInputElement | null>(null);

	function picked() {
		const files = [...(input?.files ?? [])];
		if (input) input.value = '';
		if (files.length) onfiles(files);
	}
</script>

<Button {variant} {size} class={className} {disabled} {title} onclick={() => input?.click()}>{@render children()}</Button>
<input bind:this={input} type="file" class="hidden" {accept} {multiple} onchange={picked} tabindex="-1" aria-hidden="true" />
