<script lang="ts">
	// The UI kit's gallery: every shared piece on one page, with sample words only, inside the shared shell and
	// the sample app (src/sample), so it opens with no backend. For looking at the theme and the pieces together, in
	// light and dark.
	import { toggleMode, mode } from 'mode-watcher';
	import { Badge } from '$kit/components/ui/badge/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import { Checkbox } from '$kit/components/ui/checkbox/index.js';
	import * as Dialog from '$kit/components/ui/dialog/index.js';
	import { Slider } from '$kit/components/ui/slider/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import { Input } from '$kit/components/ui/input/index.js';
	import { Label } from '$kit/components/ui/label/index.js';
	import * as Select from '$kit/components/ui/select/index.js';
	import { Switch } from '$kit/components/ui/switch/index.js';
	import * as Table from '$kit/components/ui/table/index.js';
	import * as Tabs from '$kit/components/ui/tabs/index.js';
	import { Textarea } from '$kit/components/ui/textarea/index.js';
	import * as Tooltip from '$kit/components/ui/tooltip/index.js';
	import Avatar from '$kit/ui/avatar.svelte';
	import EmptyState from '$kit/ui/empty-state.svelte';
	import Field from '$kit/ui/field.svelte';
	import Loading from '$kit/ui/loading.svelte';
	import Notice from '$kit/ui/notice.svelte';
	import Panel from '$kit/ui/panel.svelte';
	import { toast } from '$kit/ui/toast.svelte';
	import HelpTip from '$kit/ui/help-tip.svelte';
	import OptionChips from '$kit/ui/option-chips.svelte';
	import PageHeader from '$kit/ui/page-header.svelte';
	import SearchInput from '$kit/ui/search-input.svelte';
	import Segmented from '$kit/ui/segmented.svelte';
	import TimeField from '$kit/ui/time-field.svelte';
	import StatusDot from '$kit/ui/status-dot.svelte';
	import SliderField from '$kit/ui/slider-field.svelte';
	import FileButton from '$kit/ui/file-button.svelte';
	import { CAT, CATEGORY_COUNT } from '$kit/ui/category';
	import { Inbox, Moon, Plus, Sun, Trash2 } from '@lucide/svelte';

	let level = $state(50);
	let range = $state('24h');
	let chip = $state('all');
	let on = $state(true);
	let off = $state(false);
	let kind = $state('lights');
	let time = $state('17:30');
	let search = $state('');
	let volume = $state(40);
	let agreed = $state(true);
	let threshold = $state('0.75');
	let dialogOpen = $state(false);

	const KINDS = [
		{ value: 'lights', label: 'Lights' },
		{ value: 'plugs', label: 'Plugs' },
		{ value: 'sensors', label: 'Sensors' }
	];
	const ROWS = [
		{ name: 'Living room lamp', kind: 'Light', state: 'On', tone: 'success' },
		{ name: 'Office plug', kind: 'Plug', state: 'Needs setup', tone: 'warning' },
		{ name: 'Door sensor', kind: 'Sensor', state: 'Offline', tone: 'destructive' }
	] as const;
	const SWATCHES = ['background', 'card', 'muted', 'secondary', 'accent', 'primary', 'destructive', 'success', 'warning'];
	const BRAND = ['brand', 'brand-mid', 'brand-deep', 'brand-rose', 'brand-pink', 'brand-blue', 'brand-green'];
	const CHART = [62, 48, 80, 35, 55];
</script>

<Tooltip.Provider>
	<div class="max-w-5xl">
		<PageHeader title="UI kit">
			{#snippet tabs()}
				<Tabs.Root value="pieces">
					<Tabs.List>
						<Tabs.Trigger value="pieces">Pieces</Tabs.Trigger>
						<Tabs.Trigger value="colours">Colours</Tabs.Trigger>
					</Tabs.List>
				</Tabs.Root>
			{/snippet}
			{#snippet actions()}
				<Button variant="outline" size="sm" onclick={toggleMode}>
					{#if mode.current === 'dark'}<Sun /> Light mode{:else}<Moon /> Dark mode{/if}
				</Button>
			{/snippet}
		</PageHeader>

		<div class="grid gap-4 md:grid-cols-2">
			<Card.Root>
				<Card.Header>
					<Card.Title>Buttons</Card.Title>
					<Card.Description>One main action per place; the rest are quieter.</Card.Description>
				</Card.Header>
				<Card.Content class="grid gap-3">
					<div class="flex flex-wrap items-center gap-2">
						<Button><Plus /> Add</Button>
						<Button variant="secondary">Secondary</Button>
						<Button variant="outline">Outline</Button>
						<Button variant="ghost">Ghost</Button>
						<Button variant="destructive"><Trash2 /> Delete</Button>
						<Button variant="link">Link</Button>
					</div>
					<div class="flex flex-wrap items-center gap-2">
						<Button size="xs">Extra small</Button>
						<Button size="sm">Small</Button>
						<Button>Default</Button>
						<Button size="lg">Large</Button>
						<Button disabled>Disabled</Button>
					</div>
				</Card.Content>
			</Card.Root>

			<Card.Root>
				<Card.Header>
					<Card.Title>Badges and status</Card.Title>
					<Card.Description>Status colours: all is well, look at this, something is wrong.</Card.Description>
				</Card.Header>
				<Card.Content class="grid gap-3">
					<div class="flex flex-wrap items-center gap-2">
						<Badge>Default</Badge>
						<Badge variant="secondary">Secondary</Badge>
						<Badge variant="outline">Outline</Badge>
						<Badge variant="destructive">Destructive</Badge>
						<Badge class="bg-success/15 text-success">Home</Badge>
						<Badge class="bg-warning/15 text-warning">Needs setup</Badge>
					</div>
					<div class="flex flex-wrap items-center gap-4 text-sm">
						<span class="inline-flex items-center gap-2"><span class="size-2 rounded-full bg-success"></span>Online</span>
						<span class="inline-flex items-center gap-2"><span class="size-2 rounded-full bg-warning"></span>Slow</span>
						<span class="inline-flex items-center gap-2"><span class="size-2 rounded-full bg-destructive"></span>Down</span>
						<span class="inline-flex items-center gap-2"><span class="size-2 rounded-full bg-muted-foreground"></span>Not set up</span>
					</div>
					<div class="flex items-center gap-2">
						<Avatar name="Michel Habib" />
						<Avatar name="Joe" class="size-8 text-xs" />
						<Avatar name="Mark Stone" class="size-6 text-[9px]" />
					</div>
				</Card.Content>
			</Card.Root>

			<Card.Root>
				<Card.Header>
					<Card.Title>Fields</Card.Title>
					<Card.Description>A label, its control, and a line of help.</Card.Description>
				</Card.Header>
				<Card.Content class="grid gap-4">
					<div class="grid gap-2">
						<Label for="kit-name" class="gap-1.5">Name <HelpTip label="Name" text="What people call it. Shown in the menu and on every page." /></Label>
						<Input id="kit-name" value="Living room lamp" />
						<p class="text-xs text-muted-foreground">Shown wherever this thing appears.</p>
					</div>
					<div class="grid gap-2">
						<Label for="kit-kind">Kind</Label>
						<Select.Root type="single" bind:value={kind}>
							<Select.Trigger id="kit-kind" class="w-full">{KINDS.find((k) => k.value === kind)?.label}</Select.Trigger>
							<Select.Content>
								{#each KINDS as k (k.value)}<Select.Item value={k.value}>{k.label}</Select.Item>{/each}
							</Select.Content>
						</Select.Root>
					</div>
					<div class="grid gap-2">
						<Label for="kit-notes">Notes</Label>
						<Textarea id="kit-notes" placeholder="Anything worth remembering…" />
					</div>
					<div class="flex flex-wrap items-center gap-4">
						<label class="flex items-center gap-2 text-sm"><Switch bind:checked={on} /> Turns on at sunset</label>
						<label class="flex items-center gap-2 text-sm"><Switch bind:checked={off} /> Off</label>
					</div>
					<div class="flex flex-wrap items-center gap-3 text-sm">
						At <TimeField value={time} onchange={(v) => (time = v)} />
					</div>
					<p class="text-sm text-destructive" role="alert">Name: this one is already taken.</p>
					<p class="text-sm text-success" role="status">Saved.</p>
				</Card.Content>
				<Card.Footer class="justify-end gap-2">
					<Button variant="outline">Cancel</Button>
					<Button>Save</Button>
				</Card.Footer>
			</Card.Root>

			<Card.Root>
				<Card.Header>
					<Card.Title>Status, kinds and files</Card.Title>
					<Card.Description>Status lights, the eight category colours, a slider in a form, a file button.</Card.Description>
				</Card.Header>
				<Card.Content class="grid gap-4">
					<div class="flex flex-wrap items-center gap-4 text-sm">
						<span class="inline-flex items-center gap-1.5"><StatusDot tone="ok" ping />Online</span>
						<span class="inline-flex items-center gap-1.5"><StatusDot tone="warn" />Not set up</span>
						<span class="inline-flex items-center gap-1.5"><StatusDot tone="error" />Failed</span>
						<span class="inline-flex items-center gap-1.5"><StatusDot tone="info" pulse />Live</span>
						<span class="inline-flex items-center gap-1.5"><StatusDot tone="off" />Off</span>
					</div>
					<div class="flex flex-wrap gap-1.5">
						{#each Array.from({ length: CATEGORY_COUNT }, (_, i) => i + 1) as n (n)}
							<span class={['rounded-md border px-2 py-0.5 text-xs font-medium', CAT.chip[n]]}>Kind {n}</span>
						{/each}
					</div>
					<SliderField label="Speaking speed" value={level} onchange={(v) => (level = v)} reset={50} format={(v) => `${v}%`} hint="How fast Hiro speaks." />
					<div class="flex flex-wrap items-center gap-3">
						<FileButton accept="image/*" onfiles={(f) => toast.info(`Picked ${f[0].name}`)}>Upload a photo</FileButton>
						<span class="text-sm">Text with <Button variant="link" size="inline" onclick={() => toast.info('Opened')}>a link button</Button> inside.</span>
					</div>
				</Card.Content>
			</Card.Root>

			<Card.Root>
				<Card.Header>
					<Card.Title>Choices and filters</Card.Title>
					<Card.Description>One of a few, side by side; a search; chips.</Card.Description>
				</Card.Header>
				<Card.Content class="grid gap-4">
					<div class="flex flex-wrap items-center gap-2">
						<Segmented
							value={range}
							onchange={(v) => (range = v)}
							options={[
								{ value: '1h', label: '1 h', count: 3 },
								{ value: '24h', label: '24 h', count: 41 },
								{ value: '7d', label: '7 days', count: 280 }
							]}
						/>
						<SearchInput bind:value={search} placeholder="Search devices…" />
					</div>
					<OptionChips
						label="Which devices"
						value={chip}
						onchange={(v) => (chip = v)}
						options={[
							{ id: 'all', label: 'All' },
							{ id: 'online', label: 'Online' },
							{ id: 'offline', label: 'Offline' },
							{ id: 'new', label: 'New' }
						]}
					/>
					<Table.Root>
						<Table.Header>
							<Table.Row>
								<Table.Head>Name</Table.Head>
								<Table.Head>Kind</Table.Head>
								<Table.Head>Now</Table.Head>
							</Table.Row>
						</Table.Header>
						<Table.Body>
							{#each ROWS as r (r.name)}
								<Table.Row>
									<Table.Cell class="font-medium">{r.name}</Table.Cell>
									<Table.Cell class="text-muted-foreground">{r.kind}</Table.Cell>
									<Table.Cell>
										<span class="inline-flex items-center gap-2">
											<span class={['size-2 rounded-full', r.tone === 'success' ? 'bg-success' : r.tone === 'warning' ? 'bg-warning' : 'bg-destructive']}></span>{r.state}
										</span>
									</Table.Cell>
								</Table.Row>
							{/each}
						</Table.Body>
					</Table.Root>
				</Card.Content>
			</Card.Root>

			<Panel title="Messages and states" description="What a page says when something is wrong, missing or on its way.">
				<div class="grid gap-3">
					<Notice tone="error" title="The server didn't answer" message="It may be restarting. This page tries again by itself.">
						{#snippet actions()}<Button size="sm" variant="outline">Try again</Button>{/snippet}
					</Notice>
					<Notice tone="warning" message="Live updates are paused: showing what was last loaded." />
					<Notice tone="success" message="The backup finished." />
					<Notice tone="info" message="Roles are set in HiroLeague." />
					<Loading label="Asking HiroLeague…" />
					<EmptyState message="No devices yet" hint="They appear here once Home Assistant is connected.">
						{#snippet icon()}<Inbox />{/snippet}
						{#snippet actions()}<Button size="sm"><Plus /> Connect</Button>{/snippet}
					</EmptyState>
				</div>
			</Panel>

			<Panel title="More controls" description="A field with help and a way back to its default; toasts; a dialog.">
				{#snippet actions()}<Button size="sm" variant="outline" onclick={() => (dialogOpen = true)}>Open a dialog</Button>{/snippet}
				<div class="grid gap-4">
					<Field label="Match threshold" for="kit-threshold" hint="Between 0 and 1. Higher is stricter." help="How sure a match must be before it counts. Change it only if matches are wrong too often." onreset={() => (threshold = '0.75')}>
						<Input id="kit-threshold" bind:value={threshold} />
					</Field>
					<Field label="Volume" hint="{volume}%">
						<Slider type="single" bind:value={volume} max={100} step={5} />
					</Field>
					<label class="flex items-center gap-2 text-sm"><Checkbox bind:checked={agreed} /> Tell me when it is done</label>
					<div class="flex flex-wrap items-center gap-2">
						<Button size="sm" variant="outline" onclick={() => toast.success('Saved')}>Toast: saved</Button>
						<Button size="sm" variant="outline" onclick={() => toast.error("Couldn't save: the name is taken.")}>Toast: error</Button>
						<Button size="sm" variant="outline" onclick={() => toast.info('Copied')}>Toast: info</Button>
					</div>
				</div>
			</Panel>

			<Dialog.Root bind:open={dialogOpen}>
				<Dialog.Content>
					<Dialog.Header>
						<Dialog.Title>Add a device</Dialog.Title>
						<Dialog.Description>A dialog for a small task that needs an answer before going on.</Dialog.Description>
					</Dialog.Header>
					<Field label="Name" for="kit-dialog-name"><Input id="kit-dialog-name" placeholder="Hallway lamp" /></Field>
					<Dialog.Footer>
						<Button variant="outline" onclick={() => (dialogOpen = false)}>Cancel</Button>
						<Button onclick={() => ((dialogOpen = false), toast.success('Added'))}>Add</Button>
					</Dialog.Footer>
				</Dialog.Content>
			</Dialog.Root>

			<Card.Root class="md:col-span-2">
				<Card.Header>
					<Card.Title>Colours and the colour style</Card.Title>
					<Card.Description>The palette is HiroLeague's: several colours, and fades between two.</Card.Description>
				</Card.Header>
				<Card.Content class="grid gap-5">
					<div class="grid gap-2">
						<p class="accent-text-gradient text-[11px] font-bold tracking-wide uppercase">Surfaces and roles</p>
						<div class="flex flex-wrap gap-2">
							{#each SWATCHES as c (c)}
								<div class="grid w-20 gap-1 text-center text-[11px] text-muted-foreground">
									<span class="h-10 rounded-md border" style="background: var(--{c})"></span>{c}
								</div>
							{/each}
						</div>
					</div>
					<div class="grid gap-2">
						<p class="accent-text-gradient text-[11px] font-bold tracking-wide uppercase">The brand's colours</p>
						<div class="flex flex-wrap gap-2">
							{#each BRAND as c (c)}
								<div class="grid w-20 gap-1 text-center text-[11px] text-muted-foreground">
									<span class="h-10 rounded-md" style="background: var(--{c})"></span>{c.replace('brand-', '')}
								</div>
							{/each}
						</div>
					</div>
					<div class="grid gap-3 md:grid-cols-3">
						<div class="rounded-lg border p-4">
							<p class="text-xs text-muted-foreground">A title in the warm run</p>
							<p class="brand-text-gradient text-2xl font-semibold">Good evening</p>
						</div>
						<div class="brand-surface rounded-lg border p-4">
							<p class="text-xs text-muted-foreground">A surface with a breath of blue</p>
							<p class="text-2xl font-semibold tabular-nums">21.5°</p>
						</div>
						<div class="rounded-lg border p-4" style="background: linear-gradient(135deg, color-mix(in oklch, var(--card) 82%, var(--brand-mid)), var(--card) 60%)">
							<p class="text-xs text-muted-foreground">A fade from a brand colour</p>
							<p class="text-2xl font-semibold tabular-nums">3 at home</p>
						</div>
					</div>
					<div class="grid gap-2">
						<p class="accent-text-gradient text-[11px] font-bold tracking-wide uppercase">Kinds, told apart (charts, categories)</p>
						<div class="flex h-24 items-end gap-3">
							{#each CHART as h, i (i)}
								<div class="w-10 rounded-t-md" style="height: {h}%; background: linear-gradient(180deg, var(--chart-{i + 1}), color-mix(in oklch, var(--chart-{i + 1}) 55%, transparent))"></div>
							{/each}
						</div>
					</div>
				</Card.Content>
			</Card.Root>
		</div>
	</div>
</Tooltip.Provider>
