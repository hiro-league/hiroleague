<script lang="ts" module>
	export type DotTone = 'ok' | 'warn' | 'error' | 'info' | 'off';
</script>

<script lang="ts">
	// A small round light that says how something is: well (ok), look at this (warn), wrong (error), news (info) or
	// switched off (off). `pulse` for something live right now, `ping` for a ring that spreads from it. Give it a
	// `label` when no words beside it say the same, so screen readers hear it.
	// UI kit, step 3: HomeHiro, NetHiro and the admin drew these by hand (a span, rounded-full, a colour).
	import { cn } from '$kit/utils';

	interface Props {
		tone?: DotTone;
		size?: 'xs' | 'sm' | 'md';
		pulse?: boolean;
		ping?: boolean;
		/** a ring in the page's colour round it: a dot sitting over an icon's corner */
		ring?: boolean;
		label?: string;
		class?: string;
	}
	let { tone = 'ok', size = 'sm', pulse = false, ping = false, ring = false, label, class: className }: Props = $props();

	const COLOR: Record<DotTone, string> = {
		ok: 'bg-success',
		warn: 'bg-warning',
		error: 'bg-destructive',
		info: 'bg-primary',
		off: 'bg-muted-foreground/50'
	};
	const SIZE = { xs: 'size-1.5', sm: 'size-2', md: 'size-2.5' } as const;
</script>

<span
	class={cn('relative inline-flex shrink-0 rounded-full', SIZE[size], ring && 'ring-2 ring-background', className)}
	role={label ? 'img' : undefined}
	aria-label={label}
	aria-hidden={label ? undefined : true}
	title={label}
>
	{#if ping}<span class={cn('absolute inline-flex size-full animate-ping rounded-full opacity-60', COLOR[tone])}></span>{/if}
	<span class={cn('relative inline-flex size-full rounded-full', COLOR[tone], pulse && 'animate-pulse')}></span>
</span>
