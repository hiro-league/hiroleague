<script lang="ts">
	// The app's uses as the HiroLeague core has them (picked here, saved in HiroLeague): what each sends, the core's
	// profile it asks with (with today's use) and the profiles it falls back to. Profiles are edited only in
	// HiroLeague's admin: Edit opens that profile's editor there, and the card links to its AI profiles once.
	import { Badge } from '$kit/components/ui/badge/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Select from '$kit/components/ui/select/index.js';
	import Panel from '$kit/ui/panel.svelte';
	import { KeyedAction } from '$kit/state/keyed-action.svelte';
	import { AudioLines, Braces, ExternalLink, Image, Pencil } from '@lucide/svelte';
	import { AI } from '$hiro-app/ai';
	import { chainLine, modelLine, needLabels, usageText } from '$kit/hiroleague/core-ai';
	import type { CoreAi } from '$kit/hiroleague/core-ai-source.svelte';
	import { coreEditUrl, coreProfilesUrl, setAiUse } from '$kit/pages/ai/api';

	let { ai }: { ai: CoreAi } = $props();
	const ICON = { pictures: Image, sound: AudioLines, json: Braces } as const;
	const adminUrl = $derived(ai.data.data?.admin_url ?? '');
	const saving = new KeyedAction(); // one use's pick waits and fails on its own
	const pick = (use: string, profileId: string) => saving.run(use, async () => ai.data.set(await setAiUse(use, profileId || null)));
</script>

<Panel class="max-w-4xl" title="Uses" description={AI.usesAbout}>
	{#snippet actions()}
		{#if adminUrl}<Button variant="outline" size="sm" href={coreProfilesUrl(adminUrl, 'ai')} target="_blank" rel="noreferrer"
				><ExternalLink />HiroLeague's AI profiles</Button
			>{/if}
	{/snippet}
	<div class="grid gap-0 divide-y">
		{#each ai.uses as u (u.id)}
			{@const p = ai.profile(u.profile_id)}
			{@const used = p ? usageText(p) : ''}
			<div class="grid gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] sm:items-start">
				<div class="grid gap-1">
					<span class="font-medium">{u.name}</span>
					<span class="flex flex-wrap gap-1">
						{#each needLabels(u) as n (n.need)}
							{@const Icon = ICON[n.need]}
							<Badge variant="outline"><Icon />{n.label}</Badge>
						{/each}
					</span>
				</div>
				<div class="grid gap-1">
					<div class="flex items-center gap-2">
						<Select.Root type="single" value={u.profile_id ?? ''} onValueChange={(v) => pick(u.id, v)} disabled={saving.busy(u.id) || !ai.reachable}>
							<Select.Trigger class="w-full min-w-0"
								><span class="truncate"
									>{p?.name ?? (u.profile_id ? `A profile HiroLeague didn't list (${u.profile_id})` : 'No profile picked in HiroLeague')}</span
								></Select.Trigger
							>
							<Select.Content>
								{#each ai.profiles as cp (cp.id)}
									<Select.Item value={cp.id} label={cp.name}>{cp.name}<span class="ml-auto text-xs text-muted-foreground">{modelLine(cp)}</span></Select.Item>
								{/each}
							</Select.Content>
						</Select.Root>
						{#if p && adminUrl}
							<Button variant="outline" size="icon" href={coreEditUrl(adminUrl, 'ai', p.id)} target="_blank" rel="noreferrer" title="Edit this profile in HiroLeague"
								><Pencil /></Button
							>
						{/if}
					</div>
					{#if p}
						<p class="text-xs text-muted-foreground">{modelLine(p)}{used ? ` · ${used}` : ''}</p>
					{:else if !ai.fetchedAt}
						<p class="text-xs text-muted-foreground">Not known yet: HiroLeague hasn't sent its profiles.</p>
					{:else if !u.profile_id}
						<p class="text-xs text-warning">Its questions are refused until a profile is picked.</p>
					{/if}
					{#if saving.error(u.id)}<p class="text-xs text-destructive" role="alert">{saving.error(u.id)}</p>{/if}
					{#if (u.chain ?? []).length > 1}
						<p class="text-xs text-muted-foreground">Falls back: {chainLine(u, ai.profiles)}</p>
					{/if}
				</div>
			</div>
		{/each}
	</div>
	{#snippet footer()}
		<p class="text-xs text-muted-foreground">
			The profiles live in HiroLeague and are edited there, for every use of the profile (Hiro's too).{adminUrl
				? ''
				: " Set HiroLeague's admin address in Settings → HiroLeague for the Edit links."}{AI.usesNote ? ` ${AI.usesNote}` : ''}
		</p>
	{/snippet}
</Panel>
