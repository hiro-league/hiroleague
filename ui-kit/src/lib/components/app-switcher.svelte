<script lang="ts">
	// The app switcher: a grid button in the menu's head that opens every app this person may open (HiroLeague, when
	// their role opens its settings, then the apps in the core's order), to move between them. The app it is shown in
	// is marked; an app not connected to HiroLeague right now is faded (its site may still open). A tile opens the app
	// in this tab (a middle click or Ctrl+click: a new tab). The list is asked each time the grid opens, so a new app
	// or a changed role shows without a reload; the last list stays while the new one comes.
	// `load` stands in for the backend's /api/apps (the kit's gallery has no backend).
	import { Grip } from '@lucide/svelte';
	import { ApiError, errorMessage } from '$kit/api/client';
	import { listApps, type AppTile } from '$kit/api/apps';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Popover from '$kit/components/ui/popover/index.js';
	import Loading from '$kit/ui/loading.svelte';
	import Notice from '$kit/ui/notice.svelte';
	import { cn } from '$kit/utils';
	import { appIcon, coreLogo } from './app-icons';

	interface Props {
		load?: () => Promise<AppTile[]>;
		class?: string;
	}
	let { load = listApps, class: className }: Props = $props();

	let open = $state(false);
	let apps = $state<AppTile[] | null>(null);
	let error = $state('');
	let asking = 0; // only the newest answer counts, when the grid is opened twice quickly
	const noLogo = $state<Record<string, boolean>>({}); // the core's logo didn't load (an old core): its icon instead

	async function ask() {
		const mine = ++asking;
		try {
			const got = await load();
			if (mine !== asking) return;
			apps = got;
			error = '';
		} catch (e) {
			// 404: a backend from before the app switcher (not redeployed yet)
			if (mine === asking) error = e instanceof ApiError && e.status === 404 ? "This app can't list your other apps yet: it needs an update." : errorMessage(e);
		}
	}

	$effect(() => {
		if (open) void ask();
	});

	const tip = (a: AppTile) => (a.here ? `${a.title}: you're here` : a.online ? `Open ${a.title}` : `${a.title} isn't connected to HiroLeague right now`);
</script>

<Popover.Root bind:open>
	<Popover.Trigger>
		{#snippet child({ props })}
			<Button {...props} variant="ghost" size="icon-sm" class={cn('shrink-0 text-muted-foreground', className)} title="Apps" aria-label="Apps">
				<Grip />
			</Button>
		{/snippet}
	</Popover.Trigger>
	<Popover.Content align="start" class="w-80 p-2">
		{#if apps?.length}
			<nav aria-label="Apps" class="grid grid-cols-3 gap-1">
				{#each apps as a (a.extension)}
					{@const Icon = appIcon(a.icon)}
					<a
						href={a.url}
						title={tip(a)}
						aria-current={a.here ? 'page' : undefined}
						onclick={() => (open = false)}
						class={[
							'group flex min-w-0 flex-col items-center gap-1.5 rounded-lg px-1 py-3 text-center transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none',
							a.here && 'bg-primary/5 ring-1 ring-primary/30'
						]}
					>
						<span class={['relative grid size-11 place-items-center rounded-xl bg-primary/10 text-primary', !a.online && 'opacity-50']}>
							{#if a.icon === 'hiroleague' && !noLogo[a.url]}
								<img src={coreLogo(a.url)} alt="" class="size-7 object-contain" onerror={() => (noLogo[a.url] = true)} />
							{:else}
								<Icon class="size-5" />
							{/if}
							{#if !a.online}
								<span class="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full bg-muted-foreground ring-2 ring-popover" aria-hidden="true"></span>
							{/if}
						</span>
						<span class={['w-full truncate text-xs', a.here ? 'font-semibold text-foreground' : 'text-muted-foreground group-hover:text-foreground']}>{a.title}</span>
					</a>
				{/each}
			</nav>
		{:else if apps && !error}
			<p class="p-2 text-sm text-muted-foreground">No other apps yet.</p>
		{:else if !error}
			<Loading label="Asking HiroLeague…" class="p-2" />
		{/if}
		{#if error}
			<Notice size="sm" message={error} class={apps?.length ? 'mt-2' : ''} />
		{/if}
	</Popover.Content>
</Popover.Root>
