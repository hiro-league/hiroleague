<script lang="ts">
	// The line above every page of a test environment: which one it is, its switchboard's preset, and what it reaches
	// of each outside system this app uses ("Home Assistant read only · AI fake"). A real system is in the warning
	// colour and comes first: what is done there happens for real. Live and env0 say no place (place.ts), and show
	// nothing. Where the sign-in screen is off it says who everyone is. The shell draws it (app-shell.svelte) from the answer to "who is asking".
	import { FlaskConical, LockOpen, TriangleAlert, UserRound } from '@lucide/svelte';
	import { who } from '$kit/state/who.svelte';
	import { everyoneIs, inBannerOrder, MODE_MEANS, MODE_WORDS, placeOf } from './place';

	const place = $derived(placeOf(who.me));
	const everyone = $derived(place ? everyoneIs(place) : null);
</script>

{#if place}
	<div
		class="flex flex-wrap items-center gap-x-3 gap-y-0.5 border-b bg-muted/40 px-4 py-1.5 text-xs text-muted-foreground md:px-6"
		role="status"
		aria-label="Test environment"
	>
		<span class="inline-flex items-center gap-1.5 font-medium text-foreground" title="A test environment: its own copy of the data. Its switchboard says what it reaches of the real house (hiro-work switch)">
			<FlaskConical class="size-3.5" />{place.place}{place.preset ? ` · ${place.preset}` : ''}
		</span>
		{#if everyone}
			<!-- The sign-in screen is off here: who every visitor is -->
			<span class="inline-flex items-center gap-1 font-medium text-warning" title="This environment's switchboard turns the sign-in screen off, for interactive use (hiro-work switch)">
				{#if place.sign_in === 'as'}<UserRound class="size-3.5" />{:else}<LockOpen class="size-3.5" />{/if}{everyone}
			</span>
		{/if}
		{#if place.problem}
			<span class="inline-flex items-center gap-1 text-warning"><TriangleAlert class="size-3.5" />{place.problem}</span>
		{:else}
			{#each inBannerOrder(place) as s (s.id)}
				<span class={s.mode === 'real' ? 'font-medium text-warning' : ''} title="{s.name}: {MODE_MEANS[s.mode]}">
					{s.name} {MODE_WORDS[s.mode]}
				</span>
			{/each}
		{/if}
	</div>
{/if}
