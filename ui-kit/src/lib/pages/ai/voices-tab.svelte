<script lang="ts">
	// Settings → Voices from HiroLeague, for an app that speaks (its `AI.voices` in $hiro-app/ai.ts; an app without it
	// doesn't show this tab). The voice profiles, designed voices, the providers' keys and the clip cache live in
	// HiroLeague's admin (Catalog → Profiles); the app asks the core to speak and plays the clip. Here: the Speak use and
	// the voice profile it speaks with by default (picked here, saved in HiroLeague; Edit opens it in HiroLeague's admin),
	// and the core's voice profiles. While the core doesn't answer, the last list it sent, with when.
	import Panel from '$kit/ui/panel.svelte';
	import { Badge } from '$kit/components/ui/badge/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Select from '$kit/components/ui/select/index.js';
	import { dateTime } from '$kit/format/time';
	import { Action } from '$kit/state/action.svelte';
	import { Resource } from '$kit/state/resource.svelte';
	import { AudioLines, ExternalLink, Pencil, Unplug } from '@lucide/svelte';
	import { AI } from '$hiro-app/ai';
	import { coreEditUrl, coreProfilesUrl, getVoices, setDefaultVoice, type CoreVoices } from '$kit/pages/ai/api';
	import MovedCard from '$kit/pages/ai/moved-card.svelte';

	const V = AI.voices;
	const voices = new Resource<CoreVoices>((signal) => getVoices(signal), { on: ['hello'], every: 60_000 });
	const data = $derived(voices.data);
	const profiles = $derived(data?.profiles ?? []);
	const picked = $derived(profiles.find((v) => v.id === data?.default_id));
	const adminUrl = $derived(data?.admin_url ?? '');
	const saving = new Action();
	const pick = (id: string) =>
		saving.run(async () => {
			voices.set(await setDefaultVoice(id || null));
		});
</script>

{#if V}
	<div class="grid max-w-4xl gap-6">
		<Panel title="Voices from HiroLeague" description={V.about}>
			{#snippet actions()}
				{#if adminUrl}<Button variant="outline" size="sm" href={coreProfilesUrl(adminUrl, 'voice')} target="_blank" rel="noreferrer"
						><ExternalLink />HiroLeague's voice profiles</Button
					>{/if}
			{/snippet}
			<div class="grid gap-1 text-sm">
				{#if data && !data.reachable}
					<p class="mb-2 flex gap-2 text-warning">
						<Unplug class="size-4 shrink-0" />{data.error ?? "HiroLeague isn't answering"}.{data.fetched_at
							? ` The list below is as of ${dateTime(data.fetched_at)}; nothing is said until it answers.`
							: ''}
					</p>
				{/if}
				<div class="flex flex-wrap items-center gap-2">
					<span class="font-medium">Speak</span>
					<Badge variant="outline"><AudioLines />A voice clip</Badge>
				</div>
				<div class="flex items-center gap-2">
					<Select.Root type="single" value={data?.default_id ?? ''} onValueChange={(v) => pick(v)} disabled={saving.busy || !data?.reachable}>
						<Select.Trigger class="w-full max-w-sm"
							><span class="truncate">{picked?.name ?? (data ? 'No voice picked in HiroLeague' : 'Asking HiroLeague…')}</span></Select.Trigger
						>
						<Select.Content>
							{#each profiles as v (v.id)}<Select.Item value={v.id} label={v.name}
									>{v.name}<span class="ml-auto text-xs text-muted-foreground">{v.line}</span></Select.Item
								>{/each}
						</Select.Content>
					</Select.Root>
					{#if picked && adminUrl}
						<Button variant="outline" size="icon" href={coreEditUrl(adminUrl, 'voice', picked.id)} target="_blank" rel="noreferrer" title="Edit this voice profile in HiroLeague"
							><Pencil /></Button
						>
					{/if}
				</div>
				{#if picked}<p class="text-xs text-muted-foreground">{picked.line}</p>{/if}
				{#if saving.error}<p class="text-xs text-destructive">{saving.error}</p>{/if}
				<p class="text-xs text-muted-foreground">
					Picking one here saves it in HiroLeague; it is edited there. {V.pickNote}
					{#if !adminUrl}Set HiroLeague's admin address in Settings → HiroLeague for the Edit links.{/if}
				</p>
			</div>
		</Panel>

		<Panel title="HiroLeague's voice profiles" description={V.listAbout}>
			<div class="grid gap-0 divide-y text-sm">
				{#each profiles as v (v.id)}
					<div class="flex items-center gap-2 py-2.5 first:pt-0 last:pb-0">
						<span class="grid flex-1 gap-0.5">
							<span class="font-medium">{v.name}{v.id === data?.default_id ? ' · default for Speak' : ''}</span>
							<span class="text-xs text-muted-foreground">{v.line}</span>
						</span>
						{#if adminUrl}
							<Button variant="ghost" size="icon" href={coreEditUrl(adminUrl, 'voice', v.id)} target="_blank" rel="noreferrer" title="Edit in HiroLeague"
								><Pencil /></Button
							>
						{/if}
					</div>
				{:else}
					<p class="text-muted-foreground">{data ? 'HiroLeague has no voice profiles yet: make one in its admin (Catalog → Profiles → Voice profiles).' : 'Asking HiroLeague…'}</p>
				{/each}
			</div>
		</Panel>

		<MovedCard moved={V.moved} />
	</div>
{/if}
