<script lang="ts">
	// __NAME__'s home page ('/'): a place to start from. Replace it with the app's first real page, and list its tabs
	// (if any) in lib/app/menu.ts.
	import * as Card from '$kit/components/ui/card/index.js';
	import PageHeader from '$kit/ui/page-header.svelte';
</script>

<PageHeader title="Home" />

<Card.Root class="max-w-xl">
	<Card.Header>
		<Card.Title>__NAME__</Card.Title>
		<Card.Description>A new Hiro app: sign-in, the menu, Logs and Settings are already in place.</Card.Description>
	</Card.Header>
</Card.Root>
