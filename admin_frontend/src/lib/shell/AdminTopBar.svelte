<script lang="ts">
  // The admin's own bar across the top of every page, inside the shared shell (@hiroleague/ui's app-shell, its
  // `topBar`): the workspace's state, the chat, Settings and the docs. UI kit step 2b: this was the header of
  // AdminShell; the menu's collapse button, light/dark and Sign out are the shared menu's now.
  import { base } from '$app/paths';
  import { BookOpen, ExternalLink, MessagesSquare, Settings } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import { DEFAULT_ADMIN_CONFIG, docsUrl, getAdminConfig, type AdminConfig } from '$lib/api/config';
  import { chatOverlay } from '$lib/features/chat-channels/overlay/chat-overlay-store.svelte';
  import { getChatEngine } from '$lib/features/chat-channels/state/chat-engine-singleton.svelte';
  import { knowledgeEventStream } from '$lib/features/knowledge/shared/knowledge-event-stream.svelte';
  import { liveStatus, type WorkspaceStatusState } from '$lib/live/status.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import { cn } from '$kit/utils';
  import StatusDot, { type DotTone } from '$kit/ui/status-dot.svelte';

  const chatEngine = getChatEngine();
  let adminConfig = $state<AdminConfig>(DEFAULT_ADMIN_CONFIG);
  const adminDocsUrl = $derived(docsUrl(adminConfig, '/'));
  const status = $derived<WorkspaceStatusState>(liveStatus.payload?.workspace_status ?? 'stopped');
  const statusLabel = $derived(liveStatus.payload?.workspace_status_label ?? 'Workspace status unavailable');
  const liveDegraded = $derived(liveStatus.degraded || knowledgeEventStream.degraded);
  const dotLabel = $derived(
    liveDegraded ? 'Live updates disconnected — close extra Hiro Admin tabs or wait for reconnect.' : statusLabel
  );
  const DOT: Record<WorkspaceStatusState, DotTone> = {
    connected: 'ok',
    running_disconnected: 'warn',
    stopped: 'error'
  };

  onMount(() => {
    getAdminConfig()
      .then((payload) => (adminConfig = payload ?? DEFAULT_ADMIN_CONFIG))
      .catch(() => (adminConfig = DEFAULT_ADMIN_CONFIG));
  });
</script>

<h1 class="accent-text-gradient min-w-0 truncate text-lg font-semibold">Control Room</h1>
<StatusDot
  size="md"
  tone={DOT[status]}
  pulse={liveDegraded}
  label={dotLabel}
  class={cn(liveDegraded && 'rounded-full ring-2 ring-warning ring-offset-1 ring-offset-background')}
/>
<span class="hidden truncate text-xs text-muted-foreground lg:inline" title="Hiro {adminConfig.hiro_package_version}">
  {adminConfig.workspace_name ?? ''}
</span>
<!-- min-h-16: the admin's pages pin their sticky headers 4rem from the top (`top-16`), the height this bar had
     in AdminShell; it keeps that height here so they still meet it. -->
<div class="ml-auto flex min-h-16 items-center gap-2">
  <Button
    variant={chatOverlay.open ? 'default' : 'secondary'}
    size="icon-lg"
    class="relative"
    aria-pressed={chatOverlay.open}
    aria-label={chatOverlay.open ? 'Close chat overlay' : 'Open chat overlay'}
    title="Chat"
    onclick={() => chatOverlay.toggle()}
  >
    <MessagesSquare />
    <!-- Pulse when the agent is replying and the overlay is closed (unread affordance). -->
    {#if chatEngine.agentTyping && !chatOverlay.open}
      <StatusDot size="md" pulse class="absolute -top-0.5 -right-0.5 rounded-full ring-2 ring-background" />
    {/if}
  </Button>
  <!-- Quick access to workspace Settings, mirroring the menu's entry. -->
  <Button variant="outline" size="icon-lg" href={`${base}/preferences`} aria-label="Settings" title="Settings"><Settings /></Button>
  <Button
    variant="outline"
    size="lg"
    href={adminDocsUrl}
    target="_blank"
    rel="noreferrer"
    aria-label="Open Hiro docs in a new tab"
    title={`Open Hiro docs in a new tab: ${adminDocsUrl}`}
  >
    <BookOpen /><ExternalLink class="size-3.5" />
  </Button>
</div>
