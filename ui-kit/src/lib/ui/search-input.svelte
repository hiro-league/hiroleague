<script lang="ts">
	// A search box with the magnifier inside and the text bound. Four looks:
	//   plain   (the default without a label): a full-width input, the magnifier in it;
	//   inline  a bordered box with a bare input and a clear button, the focus ring drawn inside it;
	//   compact a small input for a toolbar, with a match count (or a spinner while `busy`) and a clear button;
	//   field   (the default with a label): a labelled Field with a clear button.
	import { LoaderCircle, Search, X } from '@lucide/svelte';
	import Field from '$kit/ui/field.svelte';
	import { Input } from '$kit/components/ui/input/index.js';
	import { cn } from '$kit/utils';

	type Props = {
		value?: string;
		placeholder?: string;
		class?: string;
		label?: string;
		inputClass?: string;
		onValueChange?: (value: string) => void;
		/** The number of matches, shown by the compact look. */
		count?: number;
		busy?: boolean;
		size?: 'sm' | 'md';
		variant?: 'plain' | 'inline' | 'compact' | 'field';
		/** Passed to the input when no visible label is drawn. */
		'aria-label'?: string;
	};

	let {
		value = $bindable(''),
		placeholder = 'Search…',
		class: cls,
		label,
		inputClass,
		onValueChange,
		count,
		busy = false,
		size = 'md',
		variant,
		'aria-label': ariaLabel
	}: Props = $props();
	const uid = $props.id();

	const INLINE_FIELD =
		'flex h-9 min-w-72 items-center gap-2 rounded-md border border-input bg-background px-3 font-sans text-sm shadow-xs focus-within:border-ring focus-within:ring-2 focus-within:ring-inset focus-within:ring-ring';

	const layout = $derived(variant ?? (label ? 'field' : 'plain'));
	const named = $derived(ariaLabel ?? label ?? placeholder ?? 'Search');
	const showTrailing = $derived(value.trim().length > 0 || count !== undefined || busy);
	const compactTrailing = $derived(layout === 'compact' && value.trim().length > 0);
	const inputSizeClass = $derived(size === 'sm' ? 'h-8 text-xs' : '');

	function emitChange(next: string) {
		value = next;
		onValueChange?.(next);
	}

	const onInput = (event: Event) => emitChange((event.currentTarget as HTMLInputElement).value);
	const clearValue = () => emitChange('');
</script>

{#if layout === 'plain'}
	<div class={cn('relative', cls ?? 'min-w-48 flex-1')}>
		<Search class="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
		<Input class={cn('pl-8', inputClass)} {placeholder} aria-label={named} {value} oninput={onInput} />
	</div>
{:else if layout === 'inline'}
	<label class={cn(INLINE_FIELD, cls)}>
		<Search size={15} class="shrink-0 text-muted-foreground" aria-hidden="true" />
		<input
			type="search"
			class={cn('min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground', inputClass)}
			{placeholder}
			aria-label={named}
			{value}
			oninput={onInput}
		/>
		{#if value}
			<button
				class="grid size-6 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
				type="button"
				aria-label="Clear search"
				onclick={clearValue}
			>
				<X size={14} aria-hidden="true" />
			</button>
		{/if}
	</label>
{:else if layout === 'compact'}
	<div class={cn('relative', cls)}>
		<Search size={14} class="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
		<input
			type="search"
			class={cn(
				'h-8 w-44 rounded-md border bg-background pl-7 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background sm:w-52 [&::-webkit-search-cancel-button]:hidden',
				compactTrailing ? 'pr-16' : 'pr-2',
				inputClass
			)}
			{placeholder}
			aria-label={named}
			{value}
			oninput={onInput}
		/>
		{#if compactTrailing}
			<div class="absolute top-1/2 right-1.5 flex -translate-y-1/2 items-center gap-1.5">
				{#if count !== undefined || busy}
					<span
						class="text-[10px] font-medium tabular-nums {(count ?? 0) > 0 ? 'text-brand' : 'text-muted-foreground'}"
						title={`${count ?? 0} match${count === 1 ? '' : 'es'}${busy ? ' (searching…)' : ''}`}
					>
						{#if busy}
							<LoaderCircle size={12} class="motion-safe:animate-spin" aria-hidden="true" />
						{:else}
							{count ?? 0}
						{/if}
					</span>
				{/if}
				<button
					type="button"
					onclick={clearValue}
					class="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
					aria-label="Clear search"
					title="Clear search"
				>
					<X size={13} aria-hidden="true" />
				</button>
			</div>
		{/if}
	</div>
{:else}
	<Field {label} for="{uid}-search" class={cn('min-w-[12rem]', cls)}>
		<div class="relative">
			<Search size={14} class="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
			<Input
				id="{uid}-search"
				type="search"
				class={cn('w-full pl-9', showTrailing ? 'pr-8' : '', inputSizeClass, inputClass)}
				{placeholder}
				aria-label={named}
				{value}
				oninput={onInput}
			/>
			{#if value}
				<button
					type="button"
					class="absolute top-1/2 right-1.5 grid size-6 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
					aria-label="Clear search"
					onclick={clearValue}
				>
					<X size={14} aria-hidden="true" />
				</button>
			{/if}
		</div>
	</Field>
{/if}
