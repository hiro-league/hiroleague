<script lang="ts">
	// A search box with the magnifier inside and the text bound. Four looks:
	//   plain   (the default without a label): a full-width input, the magnifier in it;
	//   inline  a wider box with a clear button;
	//   compact a small input for a toolbar, with a match count (or a spinner while `busy`) and a clear button;
	//   field   (the default with a label): a labelled Field with a clear button.
	// UI kit, step 7b: every look is shadcn-svelte's Input Group (the magnifier and the trailing parts as its addons),
	// not an input with icons laid over it by hand.
	import { Search, X } from '@lucide/svelte';
	import Field from '$kit/ui/field.svelte';
	import * as InputGroup from '$kit/components/ui/input-group/index.js';
	import { Spinner } from '$kit/components/ui/spinner/index.js';
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

	const layout = $derived(variant ?? (label ? 'field' : 'plain'));
	const named = $derived(ariaLabel ?? label ?? placeholder ?? 'Search');
	const typed = $derived(value.trim().length > 0);

	function emitChange(next: string) {
		value = next;
		onValueChange?.(next);
	}

	const onInput = (event: Event) => emitChange((event.currentTarget as HTMLInputElement).value);
	const clearValue = () => emitChange('');

	const GROUP = $derived({
		plain: cn('h-9', cls ?? 'min-w-48 flex-1'), // the caller's class replaces the default width, as before 7b
		inline: cn('h-9 min-w-72', cls),
		compact: cn('h-8 w-44 sm:w-52', cls),
		field: size === 'sm' ? 'h-8' : 'h-9'
	});
</script>

{#snippet box(id?: string)}
	<InputGroup.Root class={GROUP[layout]}>
		<InputGroup.Addon><Search class={layout === 'compact' ? 'size-3.5' : undefined} /></InputGroup.Addon>
		<InputGroup.Input
			{id}
			type="search"
			class={cn(
				'[&::-webkit-search-cancel-button]:hidden',
				(layout === 'compact' || (layout === 'field' && size === 'sm')) && 'text-xs',
				inputClass
			)}
			{placeholder}
			aria-label={named}
			{value}
			oninput={onInput}
		/>
		{#if layout !== 'plain' && typed}
			<InputGroup.Addon align="inline-end">
				{#if layout === 'compact' && (count !== undefined || busy)}
					<span
						class={['text-[10px] tabular-nums', (count ?? 0) > 0 ? 'text-brand' : 'text-muted-foreground']}
						title={`${count ?? 0} match${count === 1 ? '' : 'es'}${busy ? ' (searching…)' : ''}`}
					>
						{#if busy}<Spinner class="size-3" />{:else}{count ?? 0}{/if}
					</span>
				{/if}
				{#if typed}
					<InputGroup.Button size="icon-xs" aria-label="Clear search" title="Clear search" onclick={clearValue}><X /></InputGroup.Button>
				{/if}
			</InputGroup.Addon>
		{/if}
	</InputGroup.Root>
{/snippet}

{#if layout === 'field'}
	<Field {label} for="{uid}-search" class={cn('min-w-[12rem]', cls)}>
		{@render box(`${uid}-search`)}
	</Field>
{:else}
	{@render box()}
{/if}
