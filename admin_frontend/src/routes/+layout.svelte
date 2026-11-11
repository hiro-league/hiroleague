<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import type { Snippet } from 'svelte';
  import { ModeWatcher } from 'mode-watcher';
  import AdminShell from '$lib/shell/AdminShell.svelte';
  import { navItems } from '$lib/shell/nav';
  import { isFeatureActive } from '$lib/shell/features';
  import SignInPage from '$lib/features/sign-in/SignInPage.svelte';
  import AppsOnlyView from '$lib/features/apps/AppsOnlyView.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import { adminSession } from '$lib/runtime/admin-session.svelte';
  import '../styles/app.css';

  let { children }: { children?: Snippet } = $props();
  const pathname = $derived(page.url.pathname);
  const activePath = $derived(pathname === '/' ? 'dashboard' : pathname.split('/').filter(Boolean)[0]);
  // Guard direct navigation (typed URL / bookmark) to a hidden feature's route: the
  // nav link is gone, but the route still prerenders, so block it client-side. The
  // API is also unmounted server-side, so a rendered page would only make dead calls.
  const routeSegment = (path: string) => path.split('/').filter(Boolean)[0] ?? '';
  const blockedFeature = $derived(
    navItems.some(
      (item) => item.feature && !isFeatureActive(item.feature) && routeSegment(item.path) === activePath
    )
  );
  // Logs now scrolls with the document (sticky header + sticky filter toolbar like
  // other pages); only chats keeps the fixed-height, internally-scrolling shell.
  const mainClass = $derived(
    activePath === 'chats' ? 'h-[calc(100vh-4rem)] overflow-hidden' : ''
  );

  // Phase 6: the admin has its own sign-in. Nothing of the admin (and none of its live
  // streams) starts until someone is signed in.
  onMount(() => {
    void adminSession.check();
  });
</script>

<!-- UI kit step 1d: dark by default, light on the shell's toggle. app.html applies the saved mode
     before first paint; mode-watcher keeps the `dark` class on <html> from here on. -->
<ModeWatcher defaultMode="dark" />

{#if adminSession.state === 'checking'}
  <div class="grid min-h-screen place-items-center">
    <InlineLoading label="Loading…" />
  </div>
{:else if adminSession.state === 'unreachable'}
  <div class="grid min-h-screen place-items-center px-4 text-center">
    <div class="grid gap-2">
      <h2 class="text-lg font-semibold">The server didn't answer</h2>
      <p class="text-sm text-muted-foreground">{adminSession.error}</p>
      <button class="text-sm text-primary underline" onclick={() => void adminSession.check()}>Try again</button>
    </div>
  </div>
{:else if adminSession.state === 'signed-out'}
  <SignInPage />
{:else if activePath === 'sign-in'}
  <!-- Phase 8: signed in already; /sign-in sends the browser back to the app that asked. -->
  {@render children?.()}
{:else if !adminSession.canOpenSettings}
  <!-- Phase 8: a role that doesn't open HiroLeague's settings sees only its apps. -->
  <AppsOnlyView />
{:else}
  <AdminShell {activePath} {mainClass}>
    {#if blockedFeature}
      <div class="mx-auto max-w-md py-16 text-center">
        <h2 class="text-lg font-semibold">Not available</h2>
        <p class="mt-2 text-sm text-muted-foreground">
          This feature isn't enabled in this build.
        </p>
      </div>
    {:else}
      {@render children?.()}
    {/if}
  </AdminShell>
{/if}
