<script lang="ts">
	// A row of colours to pick from, an "Auto" (none of its own) and any colour from the system picker.
	// A drag in the system picker is one undo step (`onslide`, then `onslideend`). `used`: colours of the
	// plan's own (picked in the system picker for other items of the same sort), shown after the
	// standard ones, so they can be picked again.
	interface Props {
		colors: string[];
		used?: string[];
		value: string | null | undefined;
		auto?: string; // the first button's label; it picks none
		autoTitle?: string;
		autoColors?: string[]; // what "Auto" looks like: shown as small swatches in its button
		onpick: (c: string | null) => void;
		onslide: (c: string) => void;
		onslideend: () => void;
	}
	let { colors, used = [], value, auto = 'Auto', autoTitle, autoColors = [], onpick, onslide, onslideend }: Props = $props();
	const mine = $derived(used.filter((c) => !colors.includes(c)));
	const ring = 'ring-2 ring-primary ring-offset-1 ring-offset-background';
	const own = $derived(!!value && !colors.includes(value) && !mine.includes(value));
</script>

<div class="flex flex-wrap items-center gap-1.5">
	<button type="button" class={['flex h-6 items-center gap-1 rounded-md border px-1.5 text-xs', !value && ring]} title={autoTitle} onclick={() => onpick(null)}>
		{#if autoColors.length}
			<span class="flex overflow-hidden rounded-sm border border-foreground/20">
				{#each autoColors as c (c)}<span class="size-3.5" style:background={c}></span>{/each}
			</span>
		{/if}
		{auto}
	</button>
	{#each colors as c (c)}
		<button type="button" class={['size-6 rounded-md border', value === c && ring]} style={`background: ${c}`} title={c} aria-label={`Colour ${c}`} onclick={() => onpick(c)}
		></button>
	{/each}
	{#if mine.length}
		<span class="h-5 w-px bg-border" title="Colours this plan already uses"></span>
		{#each mine as c (c)}
			<button
				type="button"
				class={['size-6 rounded-md border', value === c && ring]}
				style={`background: ${c}`}
				title={`${c}: used in this plan`}
				aria-label={`Colour ${c}`}
				onclick={() => onpick(c)}
			></button>
		{/each}
	{/if}
	<label
		class={['relative size-6 cursor-pointer overflow-hidden rounded-md border', own && ring]}
		style={`background: ${own ? value : 'conic-gradient(red, yellow, lime, aqua, blue, magenta, red)'}`}
		title="Any colour"
	>
		<input
			type="color"
			class="absolute inset-0 cursor-pointer opacity-0"
			value={value ?? colors[0]}
			oninput={(e) => onslide(e.currentTarget.value)}
			onchange={onslideend}
		/>
	</label>
</div>
