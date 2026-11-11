<script lang="ts">
  // The admin's own layout: its colours, and the shared shell (@hiroleague/ui's app-shell: who is asking, the
  // menu, the page) with what is the admin's own passed in. UI kit step 2b: the shell was AdminShell, a sidebar
  // and frame of the admin's own; it is the same shell HomeHiro, NetHiro and TrainHiro use now, with
  //   - the admin's sign-in form where an app would send the browser to HiroLeague (signedOut),
  //   - its top bar (workspace state, chat, Settings, docs),
  //   - its "server is starting" banner,
  //   - the chat overlay and what else runs on every page (overlays),
  //   - the apps-only view for a role that doesn't open HiroLeague's settings (noPages).
  import { page } from '$app/state';
  import type { Snippet } from 'svelte';
  import AppShell from '$kit/components/app-shell.svelte';
  import { who } from '$kit/state/who.svelte';
  import AppsOnlyView from '$lib/features/apps/AppsOnlyView.svelte';
  import SignInPage from '$lib/features/sign-in/SignInPage.svelte';
  import { adminSession } from '$lib/runtime/admin-session.svelte';
  import ServerStartingBanner from '$lib/runtime/ServerStartingBanner.svelte';
  import { serverReadiness } from '$lib/runtime/server-readiness.svelte';
  import AdminRuntime from '$lib/shell/AdminRuntime.svelte';
  import AdminTopBar from '$lib/shell/AdminTopBar.svelte';
  import { ADMIN_SHELL_CONTENT_PADDING, ADMIN_SHELL_HEADER_PADDING } from '$lib/styling/admin-tokens';
  import { cn } from '$kit/utils';
  import '../styles/app.css';

  let { children }: { children?: Snippet } = $props();
  const activePath = $derived(page.url.pathname.split('/').filter(Boolean)[0] ?? 'dashboard');
  // The pages keep the padding their sticky headers were written for; only chats keeps the fixed-height,
  // internally-scrolling page.
  const mainClass = $derived(cn(ADMIN_SHELL_CONTENT_PADDING, activePath === 'chats' ? 'h-[calc(100vh-var(--app-top,4rem))] overflow-hidden' : ''));

  // The admin's session (its sign-in form, a 401 from any call, Sign out in the apps-only view) and the
  // shell's "who is asking" are kept in step: when one learns someone signed in or out, the shell asks again.
  $effect(() => {
    const session = adminSession.state;
    if ((session === 'signed-in' && who.state === 'signin') || (session === 'signed-out' && who.state === 'ok')) void who.load();
  });
</script>

<svelte:head>
  <title>Hiro Admin</title>
</svelte:head>

{#if activePath === 'sign-in' && who.state === 'ok'}
  <!-- Phase 8: signed in already; /sign-in sends the browser back to the app that asked. -->
  {@render children?.()}
{/if}

<AppShell {mainClass}>
  {#snippet signedOut()}<SignInPage />{/snippet}
  {#snippet noPages()}<AppsOnlyView />{/snippet}
  {#snippet topBar()}<AdminTopBar />{/snippet}
  {#snippet banners()}
    {#if !serverReadiness.ready}
      <div class={cn('border-b border-warning/20 bg-warning/5', ADMIN_SHELL_HEADER_PADDING)}><ServerStartingBanner /></div>
    {/if}
  {/snippet}
  {#snippet overlays()}<AdminRuntime />{/snippet}
  {#if activePath !== 'sign-in'}{@render children?.()}{/if}
</AppShell>
