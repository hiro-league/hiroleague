<script lang="ts">
	// A live figure: it counts to its new value and glows for a moment when it changes, so a number that moves is
	// seen to move. In a hidden tab (where the count's frames stop) it shows the new value at once.
	import { cubicOut } from 'svelte/easing';
	import { Tween } from 'svelte/motion';

	interface Props {
		value: number;
		format: (n: number) => string; // the number in words ("25 Mbit/s", "3.4 GB"), for every step of the count
		class?: string;
	}
	let { value, format, class: cls = '' }: Props = $props();
	const shown = Tween.of(() => value, { duration: 700, easing: cubicOut });

	let glow = $state(false);
	let last: number | null = null;
	let timer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const v = value;
		const changed = last !== null && format(v) !== format(last); // a change too small to see doesn't glow
		last = v;
		if (!changed) return;
		glow = true;
		clearTimeout(timer);
		timer = setTimeout(() => (glow = false), 900);
	});
	$effect(() => () => clearTimeout(timer));
</script>

<span class="-mx-0.5 rounded-sm px-0.5 tabular-nums transition-colors duration-700 {glow ? 'bg-foreground/10' : 'bg-transparent'} {cls}">{format(typeof document !== 'undefined' && document.hidden ? value : shown.current)}</span>
