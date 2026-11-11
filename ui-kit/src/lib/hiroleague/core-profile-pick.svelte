<script lang="ts">
	// The AI profile picker a copy's own editor has (an Ask a camera copy, the Wake word, sorting sites, the Write text
	// node), listing HiroLeague's AI profiles. "Default for <use> (<profile>)" follows the profile HiroLeague's Uses gives
	// this use; or pick one of the core's profiles, each with its model and budget. Below it, what that really tries, in
	// order, and where the picture goes. While the core doesn't answer, the last list it sent stays, with a quiet note.
	import * as Select from '$kit/components/ui/select/index.js';
	import { dateTime } from '$kit/format/time';
	import { Camera, Unplug } from '@lucide/svelte';
	import { budgetHint, chainNames, fallbacksOf, modelLine } from '$kit/hiroleague/core-ai';
	import type { CoreAi } from '$kit/hiroleague/core-ai-source.svelte';

	interface Props {
		ai: CoreAi; // the core's profiles and uses, as last known
		use: string; // Home's use: "ask", "wakeword", "sites", "write"
		value: string | null | undefined; // the copy's own profile; null follows the use's default
		onchange: (v: string | null) => void;
		picture?: boolean; // say where the picture goes
	}
	let { ai, use, value, onchange, picture = false }: Props = $props();

	const u = $derived(ai.use(use));
	const own = $derived(ai.resolve(value)); // a copy's own pick, as the core lists it
	const defaultName = $derived(ai.profile(u?.profile_id)?.name ?? 'none set in HiroLeague');
	const defaultLabel = $derived(`Default for ${u?.name ?? use} (${defaultName})`);
	const gone = $derived(!!value && ai.loaded && ai.fetchedAt !== null && !own);
	// What it tries, in order: the use's chain as the core reports it, or the picked profile's own fallbacks
	const tries = $derived(own ? fallbacksOf(own.id, ai.profiles) : (u?.chain ?? []).map((id) => ai.profile(id)).filter((p) => !!p));
	const names = $derived(own ? tries.map((p) => p.name) : u ? chainNames(u, ai.profiles) : []);
	const sentTo = $derived([...new Set(tries.map((p) => p.sent_to))]);
</script>

<div class="grid gap-1">
	<Select.Root type="single" value={own?.id ?? value ?? ''} onValueChange={(v) => onchange(v || null)}>
		<Select.Trigger class="w-full">
			<span class="truncate">{value ? (own?.name ?? (ai.loaded ? 'A profile HiroLeague no longer has' : '…')) : defaultLabel}</span>
		</Select.Trigger>
		<Select.Content>
			<Select.Item value="" label={defaultLabel} />
			{#each ai.profiles as p (p.id)}
				<Select.Item value={p.id} label={p.name}>
					<span class="grid">
						<span>{p.name}</span>
						<span class="text-xs text-muted-foreground">{modelLine(p)} · {budgetHint(p)}</span>
					</span>
				</Select.Item>
			{/each}
		</Select.Content>
	</Select.Root>
	{#if gone}
		<p class="text-xs text-destructive">HiroLeague no longer has its profile: pick another, or the default.</p>
	{:else if names.length}
		<p class="text-xs text-muted-foreground">Asks with {names.join(', then ')}.</p>
	{/if}
	{#if ai.loaded && !ai.reachable}
		<p class="flex gap-2 text-xs text-muted-foreground">
			<Unplug class="size-4 shrink-0" />HiroLeague not reachable{ai.fetchedAt ? `: the list as of ${dateTime(ai.fetchedAt)}` : ': no list of its profiles yet'}.
		</p>
	{/if}
	{#if picture && sentTo.length}
		<p class="flex gap-2 text-xs text-muted-foreground">
			<Camera class="size-4 shrink-0" />The picture goes to {sentTo[0]}{sentTo.length > 1 ? ` (or ${sentTo.slice(1).join(', or ')}, when it falls back)` : ''} with the question.
		</p>
	{/if}
</div>
