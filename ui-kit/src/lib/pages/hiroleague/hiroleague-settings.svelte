<script lang="ts">
	// Settings → HiroLeague: the app as an extension of the HiroLeague core. Set the core's address, pair once with
	// a code from the core's admin (Extensions, Add an extension), then the app stays connected in the background.
	// An app may add something below the pairing (`after`, given the status), e.g. HomeHiro's one-time family import.
	import type { Snippet } from 'svelte';
	import { APP } from '$hiro-app/app';
	import { HIROLEAGUE } from '$hiro-app/hiroleague';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import { Input } from '$kit/components/ui/input/index.js';
	import { Label } from '$kit/components/ui/label/index.js';
	import { Action } from '$kit/state/action.svelte';
	import { Draft } from '$kit/state/draft.svelte';
	import { Resource } from '$kit/state/resource.svelte';
	import { ask } from '$kit/ui/confirm.svelte';
	import Feedback from '$kit/ui/feedback.svelte';
	import {
		forgetHiroLeague,
		getHiroLeague,
		pairHiroLeague,
		setHiroLeagueAdminUrl,
		setHiroLeagueUrl,
		testHiroLeague,
		type HiroLeagueStatus
	} from './api';
	import SiteAddress from './site-address.svelte';

	let { after }: { after?: Snippet<[HiroLeagueStatus]> } = $props();

	// An address being typed is kept when the status is read again; a typed space is not a change.
	const sameAddress = (a: string, b: string) => a.trim() === b.trim();
	// The status is read every few seconds: the connection changes in the background (pairing, the core restarting).
	// The addresses follow it unless one is being typed (loaded in the fetcher, so the first answer fills them too).
	const status = new Resource(
		async () => {
			const s = await getHiroLeague();
			urlForm.load(s.url);
			adminForm.load(s.admin_url_set ?? '');
			return s;
		},
		{ every: 3000 }
	);
	const current = $derived(status.data);
	const urlForm = new Draft<string>('', {
		equal: sameAddress,
		done: 'Saved.',
		save: async (u) => {
			const s = await setHiroLeagueUrl(u);
			status.set(s);
			return s.url;
		}
	});
	// Where people open the core's admin (the Edit links); "" = derived
	const adminForm = new Draft<string>('', {
		equal: sameAddress,
		done: 'Saved.',
		save: async (u) => {
			const s = await setHiroLeagueAdminUrl(u);
			status.set(s);
			return s.admin_url_set ?? '';
		}
	});
	let code = $state('');
	const saving = urlForm.action;
	const savingAdmin = adminForm.action;
	const pairing = new Action();
	const testing = new Action();
	const forgetting = new Action();
	const busy = $derived(saving.busy || savingAdmin.busy || pairing.busy || testing.busy || forgetting.busy);

	const STATUS_TEXT: Record<string, string> = {
		no_address: 'No address yet.',
		not_paired: 'Not paired.',
		connecting: 'Connecting…',
		connected: 'Connected.',
		disconnected: 'Not connected; trying again.',
		stopped: 'Stopped.'
	};

	// A status an action answered with: the core's address is what it says, a typed admin address is kept.
	const show = (s: HiroLeagueStatus) => {
		status.set(s);
		urlForm.load(s.url, true);
		adminForm.load(s.admin_url_set ?? '');
	};
	const pair = () =>
		pairing.run(async () => {
			show(await pairHiroLeague(code));
			code = '';
			return 'Pairing… the status below says when it is connected.';
		});
	const test = () =>
		testing.run(async () => {
			const r = await testHiroLeague();
			return `${r.core.name} ${r.core.version} answered in ${r.elapsed_ms} ms.`;
		});
	const forget = async () => {
		const yes = await ask({
			title: 'Unpair from HiroLeague?',
			description: `${APP.name} stops being one of its extensions. To connect again, make a new pairing code in the core.`,
			action: 'Unpair',
			danger: true
		});
		if (yes) await forgetting.run(async () => show(await forgetHiroLeague()));
	};
</script>

<Card.Root class="max-w-xl">
	<Card.Header>
		<Card.Title>HiroLeague</Card.Title>
		<Card.Description>
			{APP.name} connects to the HiroLeague core as one of its extensions. In the core's admin, open Extensions and make
			a pairing code; type its address and code here. On the server the address is
			<code>ws://127.0.0.1:18082</code>.
		</Card.Description>
	</Card.Header>
	<Card.Content class="grid gap-4">
		<div class="grid gap-2">
			<Label for="hl-url">The core's address</Label>
			<div class="flex gap-2">
				<Input id="hl-url" bind:value={urlForm.value} placeholder="ws://127.0.0.1:18082" spellcheck="false" />
				<Button variant="outline" onclick={urlForm.save} disabled={busy || !urlForm.dirty}>Save</Button>
			</div>
			<Feedback action={saving} />
		</div>

		<!-- The app's Edit links open HiroLeague's admin at this address (what they edit is edited only there). -->
		<div class="grid gap-2">
			<Label for="hl-admin">HiroLeague's admin address</Label>
			<div class="flex gap-2">
				<Input id="hl-admin" bind:value={adminForm.value} placeholder={current?.admin_url || 'http://hiro.local'} spellcheck="false" />
				<Button variant="outline" onclick={adminForm.save} disabled={busy || !adminForm.dirty}>Save</Button>
			</div>
			<p class="text-xs text-muted-foreground">
				Where the Edit links open HiroLeague's admin ({HIROLEAGUE.edits}){HIROLEAGUE.signsInThere ? ', and where you sign in' : ''}. Empty: {current?.admin_url
					? `${current.admin_url}, from the core's address and admin port`
					: "the core's address and admin port, once connected"}. Behind a proxy, type the address people open, e.g. http://hiro.local.
			</p>
			<Feedback action={savingAdmin} />
		</div>

		<!-- The site the app declares to the core (offers.shows), a name the core sets up (sites.claim). -->
		<SiteAddress {current} disabled={busy} onsaved={show} />

		{#if current}
			<p class="text-sm {current.status === 'connected' ? 'text-muted-foreground' : 'text-warning'}">
				{STATUS_TEXT[current.status] ?? current.status}
				{#if current.status === 'connected' && current.core}
					{current.core.name} {current.core.version}{current.core.workspace ? `, workspace ${current.core.workspace}` : ''}.
				{/if}
				{#if current.error && current.status !== 'connected'}
					{current.error}
				{/if}
			</p>
		{/if}

		{#if current && current.status !== 'no_address'}
			<div class="grid gap-2">
				<Label for="hl-code">Pairing code</Label>
				<div class="flex gap-2">
					<Input id="hl-code" bind:value={code} placeholder="from the core's admin" autocomplete="off" inputmode="numeric" />
					<Button onclick={pair} disabled={busy || !code.trim()}>{current.status === 'connected' ? 'Pair again' : 'Pair'}</Button>
				</div>
				<Feedback action={pairing} />
			</div>
		{/if}
		<Feedback action={testing} />
		<Feedback action={forgetting} error={status.error} />
		{#if current}{@render after?.(current)}{/if}
	</Card.Content>
	<Card.Footer class="gap-2">
		<Button variant="outline" onclick={test} disabled={busy || current?.status !== 'connected'}>Test call</Button>
		<Button variant="ghost" onclick={forget} disabled={busy || current?.status === 'not_paired' || current?.status === 'no_address'}>
			Unpair
		</Button>
	</Card.Footer>
</Card.Root>
