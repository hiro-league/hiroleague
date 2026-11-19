<script lang="ts">
	// Beside the app's name in the menu head: which environment this page runs in (environment.ts). A dev environment
	// is a small pill, "E3", in its own colour (env0 grey, env1 to env5 the category colours 1 to 5); live is a
	// small raised "live" in the success colour. No badge where the address says neither.
	import { CAT } from '$kit/ui/category';
	import { environmentOf } from './environment';

	const env = typeof location === 'undefined' ? null : environmentOf(location.hostname, location.port);
</script>

{#if env?.kind === 'live'}
	<span class="-translate-y-1 self-start text-[10px] leading-none font-semibold text-success" title="Live on Simone">live</span>
{:else if env?.kind === 'dev'}
	<span
		class={[
			'inline-flex h-4.5 shrink-0 items-center rounded-full border px-1.5 text-[10px] leading-none font-semibold tabular-nums',
			env.n === 0 ? 'border-border bg-muted text-muted-foreground' : CAT.chip[env.n]
		]}
		title={env.n === 0 ? 'Environment 0: main, your own dev' : `Environment ${env.n}: a task's dev copy`}
	>
		E{env.n}
	</span>
{/if}
