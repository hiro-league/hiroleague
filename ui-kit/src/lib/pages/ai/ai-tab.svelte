<script lang="ts">
	// Settings → AI from HiroLeague. The app's AI questions are answered by the HiroLeague core: its AI profiles,
	// providers, local servers, AI agents and Playground live there. This shows which of the core's profiles each use
	// asks with (picked here, saved in HiroLeague), and what moved. While the core doesn't answer, the last list it sent,
	// with when. The app's words are in $hiro-app/ai.ts.
	import Panel from '$kit/ui/panel.svelte';
	import { dateTime } from '$kit/format/time';
	import { Unplug } from '@lucide/svelte';
	import { AI } from '$hiro-app/ai';
	import { CoreAi } from '$kit/hiroleague/core-ai-source.svelte';
	import MovedCard from '$kit/pages/ai/moved-card.svelte';
	import UsesCard from '$kit/pages/ai/uses-card.svelte';

	const ai = new CoreAi();
</script>

<div class="grid max-w-4xl gap-6">
	<Panel title="AI from HiroLeague" description={AI.about}>
		<div class="grid gap-2 text-sm">
			{#if !ai.loaded}
				<p class="text-muted-foreground">{ai.data.error ?? 'Asking HiroLeague…'}</p>
			{:else if ai.reachable}
				<p>Answered by <span class="font-medium">{ai.core ?? 'HiroLeague'}</span>{ai.fetchedAt ? `; its profiles as of ${dateTime(ai.fetchedAt)}` : ''}.</p>
			{:else}
				<p class="flex gap-2 text-warning">
					<Unplug class="size-4 shrink-0" />{ai.problem ?? "HiroLeague isn't answering"}.
				</p>
				<p class="text-xs text-muted-foreground">
					{ai.fetchedAt ? `The list below is as of ${dateTime(ai.fetchedAt)}.` : 'No list of its profiles yet.'} AI questions are refused until it answers again.
				</p>
			{/if}
		</div>
	</Panel>

	<UsesCard {ai} />

	{#if AI.moved}<MovedCard moved={AI.moved} />{/if}
</div>
