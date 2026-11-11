<script lang="ts">
	// Settings → HiroLeague → the app's address: the site the app declares to the core (HiroLeague's Apps card opens it,
	// and its sign-in sends people back only here). It is a NAME the core sets up on the LAN (it publishes the name and
	// points its proxy at the app), not a typed URL that someone then had to set up by hand on the server: pick the kind,
	// type the label, Save; the core's answer (or its refusal) shows.
	import { untrack } from 'svelte';
	import { APP } from '$hiro-app/app';
	import { HIROLEAGUE } from '$hiro-app/hiroleague';
	import { Button } from '$kit/components/ui/button/index.js';
	import { Input } from '$kit/components/ui/input/index.js';
	import { Label } from '$kit/components/ui/label/index.js';
	import { Draft } from '$kit/state/draft.svelte';
	import Feedback from '$kit/ui/feedback.svelte';
	import Segmented from '$kit/ui/segmented.svelte';
	import { claimSiteName, type HiroLeagueStatus, type SiteKind, type SiteNameOut } from './api';
	import { addressFor, claimSaid, examplePlaceholder, KIND_OPTIONS, SUFFIX } from './site-name';

	interface Props {
		current: HiroLeagueStatus | null;
		disabled: boolean; // another HiroLeague action is running
		onsaved: (s: HiroLeagueStatus) => void;
	}
	let { current, disabled, onsaved }: Props = $props();

	type Name = { label: string; kind: SiteKind };
	let answer = $state<SiteNameOut | null>(null); // the core's last answer, until the next Save
	// The name being typed; it follows the saved name (the page polls the status) unless a new one is being typed.
	const form = new Draft<Name>(
		{ label: '', kind: 'subdomain' },
		{
			save: async (d) => {
				answer = null;
				const r = await claimSiteName(d.label, d.kind);
				answer = r;
				onsaved(r.status);
				return { label: r.status.site_label ?? '', kind: r.status.site_kind ?? d.kind };
			}
		}
	);
	$effect(() => {
		const fresh: Name = { label: current?.site_label ?? '', kind: current?.site_kind ?? 'subdomain' };
		untrack(() => form.load(fresh));
	});

	const address = $derived(addressFor(form.value.label, form.value.kind));
	// Save stays available for the address already shown: it may be saved but not yet claimed in HiroLeague (an address
	// set before names were claimed), and claiming the same name again changes nothing (2026-11-10).
	const changed = $derived(address !== '');
	const said = $derived(answer ? claimSaid(answer) : null);
</script>

<div class="grid gap-2">
	<Label for="hl-site">{APP.name}'s address</Label>
	<div class="w-fit">
		<Segmented options={KIND_OPTIONS} value={form.value.kind} onchange={(v) => (form.value.kind = v)} label="Kind of name" />
	</div>
	<div class="flex gap-2">
		<div class="flex flex-1 items-center gap-1">
			<Input id="hl-site" bind:value={form.value.label} placeholder={examplePlaceholder(form.value.kind)} spellcheck="false" autocomplete="off" />
			<span class="text-sm whitespace-nowrap text-muted-foreground">{SUFFIX[form.value.kind]}</span>
		</div>
		<Button variant="outline" onclick={form.save} disabled={disabled || form.action.busy || !changed}>Save</Button>
	</div>
	<p class="text-xs text-muted-foreground">
		The name people open {APP.name} at{current?.site_url ? `, now ${current.site_url}` : ''}. On Save, HiroLeague sets it up
		on the home network and points it here; its Apps card links here, and it sends people back here after signing them
		in.{HIROLEAGUE.siteNote ? ` ${HIROLEAGUE.siteNote}` : ''}
	</p>
	{#if said}
		<p class="text-sm {said.ok ? 'text-success' : 'text-warning'}" role="status">{said.text}</p>
	{/if}
	<Feedback action={form.action} />
</div>
