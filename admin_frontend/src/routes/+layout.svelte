<script lang="ts">
  import { page } from '$app/state';
  import type { Snippet } from 'svelte';
  import AdminShell from '$lib/shell/AdminShell.svelte';
  import '../styles/app.css';

  let { children }: { children?: Snippet } = $props();
  const pathname = $derived(page.url.pathname);
  const activePath = $derived(pathname === '/' ? 'dashboard' : pathname.split('/').filter(Boolean)[0]);
  // Logs now scrolls with the document (sticky header + sticky filter toolbar like
  // other pages); only chats keeps the fixed-height, internally-scrolling shell.
  const mainClass = $derived(
    activePath === 'chats' ? 'h-[calc(100vh-4rem)] overflow-hidden' : ''
  );
</script>

<AdminShell {activePath} {mainClass}>
  {@render children?.()}
</AdminShell>
