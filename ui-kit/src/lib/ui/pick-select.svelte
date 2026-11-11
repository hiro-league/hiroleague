<script lang="ts">
	// A dropdown that picks one of a list. A short list is the plain select; a long one (SEARCH_FROM choices or
	// more) opens with a search box on top: type to narrow it, arrow keys and Enter pick, Escape closes.
	import * as Popover from '$kit/components/ui/popover/index.js';
	import * as Select from '$kit/components/ui/select/index.js';
	import { Check, ChevronDown, Search } from '@lucide/svelte';
	import { tick } from 'svelte';
	import { SEARCH_FROM, searched, stepped, type PickOption } from './pick';

	interface Props {
		value: string;
		options: readonly PickOption[];
		onchange: (v: string) => void;
		placeholder?: string; // shown while nothing is picked
		text?: string; // what the closed box says for the picked one, when not its label in the list
		class?: string; // the closed box
		label?: string; // what it picks, for screen readers and the search box
	}
	let { value, options, onchange, placeholder = '…', text, class: cls = 'h-8 w-full text-xs', label }: Props = $props();

	const shown = $derived(text ?? options.find((o) => o.value === value)?.label ?? value);
	const long = $derived(options.length >= SEARCH_FROM);
	let open = $state(false);
	let query = $state('');
	let at = $state(-1); // the choice the arrow keys are on
	let list = $state<HTMLElement | null>(null);
	const found = $derived(searched(options, query));

	function opened(v: boolean) {
		open = v;
		if (!v) return;
		query = '';
		at = options.findIndex((o) => o.value === value);
		void tick().then(() => show(at));
	}
	const show = (i: number) => list?.querySelector<HTMLElement>(`[data-i="${i}"]`)?.scrollIntoView({ block: 'nearest' });
	function pick(v: string) {
		open = false;
		if (v !== value) onchange(v);
	}
	function keyed(e: KeyboardEvent) {
		if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
			e.preventDefault();
			at = stepped(at, e.key === 'ArrowDown' ? 1 : -1, found.length);
			show(at);
		} else if (e.key === 'Enter') {
			e.preventDefault();
			const o = found[at] ?? (found.length === 1 ? found[0] : undefined);
			if (o) pick(o.value);
		}
	}
</script>

{#if long}
	<Popover.Root bind:open={() => open, opened}>
		<Popover.Trigger
			class={[
				'flex items-center justify-between gap-1.5 rounded-lg border border-input bg-transparent py-2 pr-2 pl-2.5 whitespace-nowrap outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 dark:hover:bg-input/50',
				cls
			]}
			aria-label={label}
			data-slot="pick-select"
		>
			<span class={['truncate', !value && 'text-muted-foreground']}>{value ? shown : placeholder}</span>
			<ChevronDown class="size-4 shrink-0 text-muted-foreground" />
		</Popover.Trigger>
		<Popover.Content class="w-(--bits-popover-anchor-width) min-w-64 gap-1 p-1" align="start">
			<div class="relative">
				<Search class="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
				<!-- svelte-ignore a11y_autofocus (the box opens to be typed in) -->
				<input
					class="h-8 w-full rounded-md border border-input bg-transparent pr-2 pl-7 text-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring"
					placeholder="Search {options.length}…"
					aria-label="Search {label ?? 'the list'}"
					autofocus
					bind:value={() => query, (v) => ((query = v), (at = v.trim() ? 0 : -1))}
					onkeydown={keyed}
				/>
			</div>
			<div bind:this={list} class="max-h-64 overflow-y-auto" role="listbox" aria-label={label}>
				{#each found as o, i (o.value)}
					<button
						type="button"
						role="option"
						aria-selected={o.value === value}
						data-i={i}
						class={['flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground', i === at && 'bg-accent text-accent-foreground']}
						onclick={() => pick(o.value)}
					>
						<span class="min-w-0 flex-1 break-words">{o.label}</span>
						{#if o.value === value}<Check class="size-3.5 shrink-0" />{/if}
					</button>
				{:else}
					<p class="px-2 py-1.5 text-xs text-muted-foreground">Nothing matches “{query.trim()}”.</p>
				{/each}
			</div>
		</Popover.Content>
	</Popover.Root>
{:else}
	<Select.Root type="single" {value} onValueChange={(v) => v && onchange(v)}>
		<Select.Trigger class={cls} aria-label={label}>{value ? shown : placeholder}</Select.Trigger>
		<Select.Content>{#each options as o (o.value)}<Select.Item value={o.value} label={o.label} />{/each}</Select.Content>
	</Select.Root>
{/if}
