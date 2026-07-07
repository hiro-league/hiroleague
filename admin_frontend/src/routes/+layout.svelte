<script lang="ts">
  import { page } from '$app/state';
  import type { Snippet } from 'svelte';
  import AdminShell from '$lib/shell/AdminShell.svelte';
  import { navItems } from '$lib/shell/nav';
  import { isFeatureActive } from '$lib/shell/features';
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
</script>

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
