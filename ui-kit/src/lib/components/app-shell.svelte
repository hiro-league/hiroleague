<script lang="ts">
	// The app around every page: who is asking decides what shows (the signed-out view, the "no access" page, or
	// the app), then the menu beside the page. The same in every Hiro app (UI kit, step 1c: this was each app's
	// routes/+layout.svelte); what an app adds of its own comes in as snippets:
	//   signedOut - what a signed-out visitor sees. Left out: off to HiroLeague's sign-in (an app). The HiroLeague
	//               core, where people sign in, gives its sign-in form here.
	//   topBar    - a bar across the top of the page, beside the menu (left out: none; the menu holds everything)
	//   banners   - lines above every page (the server is starting, the connection dropped)
	//   overlays  - what floats over every page (a chat window, toasts)
	//   noPages   - what someone signed in sees when their role has no page here (the HiroLeague core shows its
	//               apps to a role that doesn't open its settings). Left out: the first page says it isn't theirs.
	// `mainClass` adds to the page area's classes (its padding, a fixed height for a page that scrolls inside).
	import type { Snippet } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { ModeWatcher } from 'mode-watcher';
	import { errorMessage } from '$kit/api/client';
	import { APP } from '$hiro-app/app';
	import { Button } from '$kit/components/ui/button/index.js';
	import * as Card from '$kit/components/ui/card/index.js';
	import * as Sidebar from '$kit/components/ui/sidebar/index.js';
	import { firstPage, pageAllowed } from '$kit/state/pages';
	import { cn } from '$kit/utils';
	import { isBool, persisted } from '$kit/state/persisted.svelte';
	import { who } from '$kit/state/who.svelte';
	import ConfirmHost from '$kit/ui/confirm-host.svelte';
	import ErrorBar from '$kit/ui/error-bar.svelte';
	import ToastHost from '$kit/ui/toast-host.svelte';
	import AppSidebar from './app-sidebar.svelte';
	import NoAccess from './no-access.svelte';
	import NotYours from './not-yours.svelte';
	import { isWidth, SIDEBAR_DEFAULT } from './sidebar-width';
	import ToHiroLeague from './to-hiroleague.svelte'; // Phase 8: signing in is HiroLeague's

	interface Props {
		children: Snippet;
		signedOut?: Snippet;
		topBar?: Snippet;
		banners?: Snippet;
		overlays?: Snippet;
		noPages?: Snippet;
		mainClass?: string;
	}
	let { children, signedOut, topBar, banners, overlays, noPages, mainClass }: Props = $props();

	// Sidebar open or collapsed, remembered in this browser (the component's own cookie is never read
	// back, since the app has no server rendering).
	const sidebarOpen = persisted('sidebar.open', true, isBool);
	// Its width, dragged by its edge.
	const sidebarWidth = persisted('sidebar.width', SIDEBAR_DEFAULT, isWidth);

	// The top bar's height, for what sticks under it (a page's header, its filter bar): --app-top, 0 with no bar.
	let barHeight = $state(0);
	$effect(() => {
		document.documentElement.style.setProperty('--app-top', topBar ? `${barHeight}px` : '0px');
		return () => document.documentElement.style.removeProperty('--app-top');
	});

	const here = $derived(page.route.id);
	// A page that shows alone, with no sign-in and no menu (the app's `openRoutes`, e.g. HomeHiro's TV screen).
	const alone = (id: string | null) => !!id && APP.openRoutes.includes(id);

	// Who is asking decides what shows: the signed-out view, the "no access" page, or the app
	// (docs/users-and-access.md). If the backend can't say, the app shows and its pages say why.
	if (!alone(page.route.id)) void who.load();

	// Someone whose role has no home page (in HomeHiro, a kid) starts on the first page they have (My room).
	$effect(() => {
		if (who.state !== 'ok' || here !== '/' || pageAllowed(who.me, '/')) return;
		const to = firstPage(who.me);
		if (to) void goto(resolve(to as '/'), { replaceState: true });
	});
</script>

<svelte:head>
	<title>{APP.name}</title>
</svelte:head>

<!-- Dark by default; the sidebar has a toggle. app.html applies the saved mode before first paint. -->
<ModeWatcher defaultMode="dark" />
<ConfirmHost />
<ErrorBar />
<ToastHost />

{#if alone(here)}
	{@render children()}
{:else if who.state === 'loading'}
	<!-- asking who this is: a moment, nothing to show yet -->
{:else if who.state === 'signin'}
	{#if signedOut}{@render signedOut()}{:else}<ToHiroLeague />{/if}
{:else if who.state === 'blocked'}
	<NoAccess />
{:else if noPages && who.state === 'ok' && firstPage(who.me) === null}
	{@render noPages()}
{:else}
<Sidebar.Provider bind:open={sidebarOpen.current} style="--sidebar-width: {sidebarWidth.current}px">
	<AppSidebar width={sidebarWidth.current} onwidth={(px) => (sidebarWidth.current = px)} />
	<Sidebar.Inset class="min-w-0">
		<!-- The collapse button is in the sidebar; on phones the sidebar is hidden, so it opens from here.
		     With a top bar, the bar shows on every screen and holds that button on phones. -->
		<header class={['flex min-h-12 items-center gap-2 border-b px-3', topBar ? 'sticky top-0 z-30 bg-background/85 backdrop-blur' : 'md:hidden']} bind:offsetHeight={barHeight}>
			<Sidebar.Trigger class="md:hidden" />
			{@render topBar?.()}
		</header>
		{@render banners?.()}
		<!-- min-w-0: let wide tables scroll inside their box instead of widening the page -->
		<main class={cn('min-w-0 flex-1 p-4 md:p-6', mainClass)}>
			<!-- A page that throws while it draws or updates shows why, instead of going blank. -->
			<svelte:boundary onerror={(e) => console.error(e)}>
				{#if pageAllowed(who.me, here) || who.state === 'error'}
					{@render children()}
				{:else}
					<NotYours />
				{/if}
				{#snippet failed(error, reset)}
					<Card.Root class="max-w-xl">
						<Card.Header>
							<Card.Title>This page stopped working</Card.Title>
							<Card.Description class="break-words">{errorMessage(error)}</Card.Description>
						</Card.Header>
						<Card.Footer class="gap-2">
							<Button onclick={reset}>Try again</Button>
							<Button variant="outline" onclick={() => location.reload()}>Reload</Button>
						</Card.Footer>
					</Card.Root>
				{/snippet}
			</svelte:boundary>
		</main>
	</Sidebar.Inset>
</Sidebar.Provider>
{@render overlays?.()}
{/if}
