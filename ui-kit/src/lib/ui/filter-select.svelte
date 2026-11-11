<script lang="ts">
	// A filter dropdown for a toolbar: a list of choices where the first ("All …", the placeholder) means no filter,
	// optionally with a button that clears it. `layout="field"` is a labelled field (the label above); `"inline"`
	// is one toolbar row (label, box and clear button side by side).
	// UI kit, step 3c: from the HiroLeague admin's AdminFilterBarSelect.
	import { X } from '@lucide/svelte';
	import { Button } from '$kit/components/ui/button/index.js';
	import Field from '$kit/ui/field.svelte';
	import PickSelect from '$kit/ui/pick-select.svelte';
	import { cn } from '$kit/utils';

	type Option = { value: string; label: string };

	interface Props {
		label?: string;
		value?: string;
		options?: readonly Option[];
		placeholder?: string; // the empty choice ("All …")
		class?: string;
		selectClass?: string;
		onValueChange?: (value: string) => void;
		clearable?: boolean; // a clear button while something is picked
		onClear?: () => void; // instead of resetting to the empty choice
		layout?: 'field' | 'inline';
		title?: string;
	}

	let {
		label,
		value = $bindable(''),
		options = [],
		placeholder,
		class: className,
		selectClass,
		onValueChange,
		clearable = false,
		onClear,
		layout = 'field',
		title
	}: Props = $props();
	const uid = $props.id();

	const choices = $derived(placeholder ? [{ value: '', label: placeholder }, ...options] : options);

	function pick(v: string) {
		value = v;
		onValueChange?.(value);
	}

	function clearValue() {
		if (onClear) {
			onClear();
			return;
		}
		value = '';
		onValueChange?.('');
	}

	const CLEAR_BUTTON = 'size-8 shrink-0 text-destructive hover:bg-destructive/15 hover:text-destructive';
</script>

{#if layout === 'inline'}
	{#if label}
		<span class="text-sm font-semibold text-muted-foreground">{label}</span>
	{/if}
	<div class={cn('flex items-center gap-0.5', className)}>
		<span class="inline-flex min-w-0" {title}>
			<PickSelect {value} options={choices} onchange={pick} {placeholder} label={label ?? placeholder} class={cn('h-8 min-w-0 text-sm', selectClass)} />
		</span>
		<div class="inline-flex size-8 shrink-0 items-center justify-center">
			{#if clearable && value.trim()}
				<Button variant="ghost" size="icon" class={CLEAR_BUTTON} onclick={clearValue} title="Clear filter" aria-label="Clear filter">
					<X size={15} strokeWidth={2} />
				</Button>
			{/if}
		</div>
	</div>
{:else}
	<Field {label} for="{uid}-pick" class={cn('min-w-[10rem]', className)}>
		<div class="flex items-center gap-0.5">
			<span class="flex min-w-0 flex-1" {title}>
				<PickSelect id="{uid}-pick" {value} options={choices} onchange={pick} {placeholder} label={label ?? placeholder} class={cn('h-8 w-full text-sm', selectClass)} />
			</span>
			{#if clearable && value.trim()}
				<Button variant="ghost" size="icon" class={CLEAR_BUTTON} onclick={clearValue} title="Clear filter" aria-label="Clear filter">
					<X size={15} strokeWidth={2} />
				</Button>
			{/if}
		</div>
	</Field>
{/if}
