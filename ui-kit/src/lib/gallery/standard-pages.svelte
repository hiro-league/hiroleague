<script lang="ts">
	// The Standard pages tab: the four pages every Hiro app can mount from the kit (src/lib/pages), what each is for,
	// and the parts that run with no backend. A part that needs its backend is described, not faked.
	import { Badge } from '$kit/components/ui/badge/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import { Input } from '$kit/components/ui/input/index.js';
	import { Label } from '$kit/components/ui/label/index.js';
	import Panel from '$kit/ui/panel.svelte';
	import SearchInput from '$kit/ui/search-input.svelte';
	import Segmented from '$kit/ui/segmented.svelte';
	import { ChevronRight } from '@lucide/svelte';

	let view = $state<'problems' | 'all'>('problems');
	let span = $state('24h');
	let search = $state('');

	// Made-up lines, as the logs page lists them (time, level, area, message).
	const LINES = [
		{ at: 'Today, 1:15:46 PM', level: 'ERROR', area: 'channels', message: 'The WhatsApp plugin stopped answering; restarting it.' },
		{ at: 'Today, 1:02:10 PM', level: 'WARNING', area: 'agent', message: 'The model took 14 s to answer (usually 3 s).' },
		{ at: 'Yesterday, 11:57:03 PM', level: 'WARNING', area: 'http', message: 'A device signed in with an old pairing code.' }
	];
	const levelClass = (l: string) => (l === 'ERROR' ? 'bg-destructive/15 text-destructive' : 'bg-warning/15 text-warning');

	const PAGES = [
		{
			id: 'pages/logs',
			title: 'Logs',
			what: "The app's log lines (problems or everything, how far back, which area, a search), grouped when they repeat, each opening to its traceback; a second tab lists the AI requests.",
			needs: 'The app reading its own log files over its API (pages/logs/api.ts). Used by HomeHiro, NetHiro and TrainHiro.'
		},
		{
			id: 'pages/users',
			title: 'Users',
			what: 'The people and their roles (the People and Roles tabs): who may do what in this app, with each person opening in a side panel.',
			needs: "HiroLeague's people and roles, read through the app's API (pages/users/api.ts)."
		},
		{
			id: 'pages/hiroleague',
			title: 'HiroLeague',
			what: "Settings for the app as an extension of the HiroLeague core: its address, pairing once with a code, the connection's state.",
			needs: "The core's extension API (pages/hiroleague/api.ts). The address form below shows how it looks."
		},
		{
			id: 'pages/ai',
			title: 'AI',
			what: "The core's AI as this app uses it: the AI profiles the app's jobs run on, and the voices (the AI and Voices tabs).",
			needs: 'The core AI source (hiroleague/core-ai-source.svelte.ts) and the AI API (pages/ai/api.ts); apps that use the core AI.'
		}
	];
</script>

<div class="grid gap-4">
	<Card.Root>
		<Card.Header>
			<Card.Title>The four standard pages</Card.Title>
			<Card.Description>
				Pages every Hiro app mounts from the kit instead of writing its own. Each reads the app's facts at
				<code class="rounded bg-muted px-1 text-xs">$hiro-app</code> and talks to the app's own backend, so only the parts that do
				not need one can run here.
			</Card.Description>
		</Card.Header>
		<Card.Content class="grid gap-3 md:grid-cols-2">
			{#each PAGES as p (p.id)}
				<div class="grid gap-1 rounded-lg border p-3">
					<div class="flex items-center gap-2"><span class="font-medium">{p.title}</span><Badge variant="outline">{p.id}</Badge></div>
					<p class="text-sm">{p.what}</p>
					<p class="text-xs text-muted-foreground">Needs: {p.needs}</p>
				</div>
			{/each}
		</Card.Content>
	</Card.Root>

	<Panel title="Logs: the toolbar and a few lines" description="Made-up lines, to see the look. The real page reads the app's log files.">
		<div class="grid gap-3">
			<div class="flex flex-wrap items-center gap-2">
				<Segmented
					size="sm"
					label="What to show"
					value={view}
					onchange={(v) => (view = v)}
					options={[
						{ value: 'problems', label: 'Problems' },
						{ value: 'all', label: 'Everything' }
					]}
				/>
				<Segmented
					size="sm"
					label="How far back"
					value={span}
					onchange={(v) => (span = v)}
					options={[
						{ value: '1h', label: '1 h' },
						{ value: '24h', label: '24 h' },
						{ value: '7d', label: '7 days' }
					]}
				/>
				<SearchInput bind:value={search} placeholder="Search the lines and tracebacks…" class="min-w-56 flex-1" />
			</div>
			<ul class="divide-y rounded-md border">
				{#each LINES.filter((l) => l.message.toLowerCase().includes(search.toLowerCase())) as l (l.at)}
					<li class="flex min-w-0 items-start gap-x-3 px-3 py-2 text-sm">
						<ChevronRight class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
						<span class="w-44 shrink-0 text-xs leading-5 whitespace-nowrap text-muted-foreground tabular-nums">{l.at}</span>
						<span class={['w-16 shrink-0 rounded px-1.5 text-center text-xs leading-5 font-medium', levelClass(l.level)]}>{l.level}</span>
						<span class="hidden w-24 shrink-0 text-xs leading-5 text-muted-foreground md:inline">{l.area}</span>
						<span class="min-w-0 flex-1 truncate leading-5">{l.message}</span>
					</li>
				{/each}
			</ul>
		</div>
	</Panel>

	<Panel title="HiroLeague: the app's address" description="The address form as it looks, disabled: on Save the app asks the core to set up the name.">
		<div class="grid gap-2">
			<Label for="gallery-site">Home's address</Label>
			<div class="w-fit">
				<Segmented
					size="sm"
					label="Kind of name"
					value="subdomain"
					onchange={() => {}}
					options={[
						{ value: 'subdomain', label: 'A name on hiro.local' },
						{ value: 'local', label: 'A .local name' }
					]}
				/>
			</div>
			<div class="flex gap-2">
				<div class="flex flex-1 items-center gap-1">
					<Input id="gallery-site" value="home" disabled />
					<span class="text-sm whitespace-nowrap text-muted-foreground">.hiro.local</span>
				</div>
				<Button variant="outline" disabled>Save</Button>
			</div>
		</div>
	</Panel>
</div>
