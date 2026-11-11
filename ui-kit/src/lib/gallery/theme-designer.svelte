<script lang="ts">
	// The Theme designer: every token of the Hiro palette (theme.css), light and dark side by side, each with a colour
	// picker and a text box (hex or any CSS colour). An edit applies at once to the whole page (the CSS variables on
	// <html>, for the mode shown), so the rest of the gallery previews the theme. "Copy theme.css" writes only the
	// tokens that differ from the kit, as the app's own theme.css, to paste into the app and commit.
	import { mode } from 'mode-watcher';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import { Textarea } from '$kit/components/ui/textarea/index.js';
	import { persisted } from '$kit/state/persisted.svelte';
	import Segmented from '$kit/ui/segmented.svelte';
	import { toast } from '$kit/ui/toast.svelte';
	import { Check, Copy, RotateCcw, Upload } from '@lucide/svelte';
	import {
		ALL_TOKENS, buildCss, countEdits, effective, emptyEdits, isEdits, KIT, onlyChanges, parseTheme, resolveVars, TOKEN_GROUPS,
		type Edits, type Mode
	} from './theme-tokens';

	// The edits and whether they show, kept in this browser (a convenience, not shared).
	const store = persisted('gallery.theme', { edits: emptyEdits(), useEdits: true }, isEdits);
	const edits = $derived(store.current.edits);
	const useEdits = $derived(store.current.useEdits);
	const shown: Edits = $derived(useEdits ? edits : emptyEdits());
	const current: Mode = $derived(mode.current === 'dark' ? 'dark' : 'light');
	const changed = $derived(countEdits(edits));
	const css = $derived(buildCss(edits));
	let loadText = $state('');
	let loading = $state(false);
	let copied = $state(false);

	// Apply the shown mode's values to the page; the other mode's (and a reset token's) go back to the stylesheet's.
	$effect(() => {
		const root = document.documentElement;
		const values = shown[current];
		for (const n of ALL_TOKENS) {
			if (values[n] !== undefined) root.style.setProperty(`--${n}`, values[n]);
			else root.style.removeProperty(`--${n}`);
		}
	});
	$effect(() => () => {
		for (const n of ALL_TOKENS) document.documentElement.style.removeProperty(`--${n}`);
	});

	/** A hex for the colour picker (it only takes #rrggbb); anything the browser can draw is turned to one. */
	function hexOf(value: string): string {
		if (/^#[0-9a-f]{6}$/i.test(value)) return value.toLowerCase();
		if (/^#[0-9a-f]{3}$/i.test(value)) return '#' + [...value.slice(1)].map((c) => c + c).join('').toLowerCase();
		const ctx = document.createElement('canvas').getContext('2d');
		if (!ctx || !CSS.supports('color', value)) return '#000000';
		ctx.fillStyle = value;
		ctx.fillRect(0, 0, 1, 1);
		const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
		return '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');
	}
	const hexFor = (name: string, m: Mode) => hexOf(resolveVars(effective(name, m, edits), m, edits));

	const copyEdits = (): Edits => ({ light: { ...edits.light }, dark: { ...edits.dark } });
	function setToken(name: string, m: Mode, value: string) {
		const next = copyEdits();
		if (value === KIT[m][name]) delete next[m][name];
		else next[m][name] = value;
		store.current = { ...store.current, edits: next };
	}
	function resetToken(name: string) {
		const next = copyEdits();
		delete next.light[name];
		delete next.dark[name];
		store.current = { ...store.current, edits: next };
	}
	const resetAll = () => (store.current = { ...store.current, edits: emptyEdits() });

	function typed(name: string, m: Mode, el: HTMLInputElement) {
		const v = el.value.trim();
		if (v && CSS.supports('color', v)) setToken(name, m, v);
		else el.value = effective(name, m, edits); // not a colour: back to what it was
	}

	async function copy() {
		try {
			await navigator.clipboard.writeText(css);
			copied = true;
			setTimeout(() => (copied = false), 2500);
			toast.success('theme.css copied');
		} catch {
			toast.error("Couldn't copy: select the text below and copy it.");
		}
	}
	function load() {
		const parsed = onlyChanges(parseTheme(loadText));
		if (!countEdits(parsed)) {
			toast.error('No theme tokens found in that text.');
			return;
		}
		store.current = { edits: parsed, useEdits: true };
		loadText = '';
		loading = false;
		toast.success(`Loaded ${countEdits(parsed)} edited values`);
	}
</script>

<div class="grid gap-4">
	<Card.Root>
		<Card.Header>
			<Card.Title>Theme designer</Card.Title>
			<Card.Description>
				Change a token and the whole page changes with it, so the Pieces tab previews the theme. The tokens live in
				<code class="rounded bg-muted px-1 text-xs">ui-kit/src/lib/theme.css</code>; a theme made here is a file of overrides for one app.
				Switch Light / Dark mode to see the mode you are editing.
			</Card.Description>
		</Card.Header>
		<Card.Content class="flex flex-wrap items-center gap-3">
			<Segmented
				label="Preview"
				size="sm"
				value={useEdits}
				onchange={(v) => (store.current = { ...store.current, useEdits: v })}
				options={[
					{ value: false, label: 'Hiro (default)', title: 'The kit as it is' },
					{ value: true, label: 'My edits', count: changed }
				]}
			/>
			<span class="text-sm text-muted-foreground">Showing {current} mode.</span>
			<Button variant="outline" size="sm" disabled={!changed} onclick={resetAll}><RotateCcw /> Reset all</Button>
		</Card.Content>
	</Card.Root>

	{#each TOKEN_GROUPS as group (group.title)}
		<Card.Root>
			<Card.Header><Card.Title class="text-base">{group.title}</Card.Title></Card.Header>
			<Card.Content class="grid gap-1 overflow-x-auto">
				<div class="grid min-w-[34rem] grid-cols-[9rem_1fr_1fr_2rem] items-center gap-x-3 text-xs text-muted-foreground">
					<span>Token</span><span>Light</span><span>Dark</span><span></span>
				</div>
				{#each group.tokens as name (name)}
					{@const isEdited = edits.light[name] !== undefined || edits.dark[name] !== undefined}
					<div class="grid min-w-[34rem] grid-cols-[9rem_1fr_1fr_2rem] items-center gap-x-3 border-t py-1.5">
						<code class={['text-xs', isEdited && 'font-semibold text-primary']}>--{name}</code>
						{#each ['light', 'dark'] as const as m (m)}
							<div class="flex min-w-0 items-center gap-2">
								<input
									type="color"
									class="h-8 w-10 shrink-0 cursor-pointer rounded border bg-transparent p-0.5"
									aria-label="{name}, {m}"
									value={hexFor(name, m)}
									oninput={(e) => setToken(name, m, e.currentTarget.value)}
								/>
								<input
									class={['h-8 min-w-0 flex-1 rounded-md border bg-transparent px-2 font-mono text-xs', edits[m][name] !== undefined && 'border-primary']}
									aria-label="{name} value, {m}"
									value={effective(name, m, edits)}
									onchange={(e) => typed(name, m, e.currentTarget)}
									spellcheck="false"
								/>
							</div>
						{/each}
						<Button variant="ghost" size="icon-xs" disabled={!isEdited} title="Back to the kit's value" aria-label="Reset {name}" onclick={() => resetToken(name)}><RotateCcw /></Button>
					</div>
				{/each}
			</Card.Content>
		</Card.Root>
	{/each}

	<Card.Root>
		<Card.Header>
			<Card.Title class="text-base">The colour styles</Card.Title>
			<Card.Description>Built from the tokens above, so they follow every edit.</Card.Description>
		</Card.Header>
		<Card.Content class="grid gap-3 md:grid-cols-4">
			<div class="rounded-lg border p-4">
				<p class="text-xs text-muted-foreground">brand-text-gradient</p>
				<p class="brand-text-gradient text-2xl font-semibold">Good evening</p>
			</div>
			<div class="rounded-lg border p-4">
				<p class="text-xs text-muted-foreground">accent-text-gradient</p>
				<p class="accent-text-gradient text-2xl font-semibold">Settings</p>
			</div>
			<div class="brand-surface rounded-lg border p-4">
				<p class="text-xs text-muted-foreground">brand-surface</p>
				<p class="text-2xl font-semibold tabular-nums">21.5°</p>
			</div>
			<div class="rounded-lg border p-4" style="background: linear-gradient(145deg, color-mix(in oklch, var(--background) 90%, var(--brand-deep)), var(--background) 42%, color-mix(in oklch, var(--background) 91%, var(--secondary)))">
				<p class="text-xs text-muted-foreground">The page's fade (body)</p>
				<p class="text-2xl font-semibold">Background</p>
			</div>
		</Card.Content>
	</Card.Root>

	<Card.Root>
		<Card.Header>
			<Card.Title class="text-base">theme.css for an app</Card.Title>
			<Card.Description>
				Only the tokens that differ from the kit. Paste it into the app's
				<code class="rounded bg-muted px-1 text-xs">frontend/src/lib/app/theme.css</code> (HomeHiro, NetHiro, TrainHiro) or
				<code class="rounded bg-muted px-1 text-xs">admin_frontend/src/lib/app/theme.css</code> (the admin), then commit and deploy that app.
			</Card.Description>
		</Card.Header>
		<Card.Content class="grid gap-3">
			<div class="flex flex-wrap items-center gap-2">
				<Button size="sm" onclick={copy}>{#if copied}<Check /> Copied{:else}<Copy /> Copy theme.css{/if}</Button>
				<Button size="sm" variant="outline" onclick={() => (loading = !loading)}><Upload /> Load theme.css</Button>
			</div>
			{#if loading}
				<div class="grid gap-2">
					<Textarea bind:value={loadText} rows={6} class="font-mono text-xs" placeholder={':root {\n\t--primary: #006bb3;\n}'} aria-label="theme.css to load" />
					<div class="flex gap-2">
						<Button size="sm" disabled={!loadText.trim()} onclick={load}>Load</Button>
						<Button size="sm" variant="ghost" onclick={() => ((loading = false), (loadText = ''))}>Cancel</Button>
					</div>
				</div>
			{/if}
			<Textarea value={css} readonly rows={Math.min(18, css.split('\n').length + 1)} class="font-mono text-xs" aria-label="theme.css" />
		</Card.Content>
	</Card.Root>
</div>
