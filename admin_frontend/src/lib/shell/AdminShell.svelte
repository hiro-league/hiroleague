<script lang="ts">
  import { base } from '$app/paths';
  import {
    Activity,
    BookOpen,
    Brain,
    Cpu,
    Database,
    ExternalLink,
    Grid2X2,
    KeyRound,
    List,
    Menu,
    MessageSquare,
    MessagesSquare,
    Moon,
    PanelLeftClose,
    PanelLeftOpen,
    Server,
    Settings2,
    Sun,
    User,
    Workflow
  } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import type { Snippet } from 'svelte';
  import { DEFAULT_ADMIN_CONFIG, docsUrl, getAdminConfig, type AdminConfig } from '$lib/api/config';
  import Button from '$lib/components/ui/button.svelte';
  import { liveStatus, type WorkspaceStatusState } from '$lib/live/status.svelte';
  import { createShellPreferences } from '$lib/preferences/shell-preferences.svelte';
  import { ADMIN_SHELL_CONTENT_PADDING, ADMIN_SHELL_HEADER_PADDING } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import { navItems } from './nav';
  import { getChatEngine } from '$lib/features/chat-channels/state/chat-engine-singleton.svelte';
  import { chatOverlay } from '$lib/features/chat-channels/overlay/chat-overlay-store.svelte';
  import GlobalChatOverlay from '$lib/features/chat-channels/overlay/GlobalChatOverlay.svelte';
  import ChatChannelClearMessagesModal from '$lib/features/chat-channels/modals/ChatChannelClearMessagesModal.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';

  let {
    activePath = 'dashboard',
    mainClass = '',
    children
  }: { activePath?: string; mainClass?: string; children?: Snippet } = $props();
  const prefs = createShellPreferences();
  // Create the shared chat engine here, in the always-mounted shell, so it owns the
  // controller's $effect/$derived for the whole session. The /chats page and the
  // global overlay both reuse this exact instance via getChatEngine().
  const chatEngine = getChatEngine();
  let adminConfig = $state<AdminConfig>(DEFAULT_ADMIN_CONFIG);
  const adminDocsUrl = $derived(docsUrl(adminConfig, '/'));
  const headerWorkspaceName = $derived(adminConfig.workspace_name ?? 'unknown');
  const headerStatus = $derived(liveStatus.payload?.workspace_status ?? 'stopped');
  const headerStatusLabel = $derived(
    liveStatus.payload?.workspace_status_label ?? 'Workspace status unavailable'
  );

  const groups = $derived(
    navItems.reduce<Record<string, typeof navItems>>((acc, item) => {
      acc[item.group] = [...(acc[item.group] ?? []), item];
      return acc;
    }, {})
  );

  const iconMap = {
    activity: Activity,
    book: BookOpen,
    brain: Brain,
    cpu: Cpu,
    database: Database,
    grid: Grid2X2,
    key: KeyRound,
    list: List,
    message: MessageSquare,
    server: Server,
    settings: Settings2,
    user: User,
    workflow: Workflow
  };

  function navHref(path: string) {
    if (path.startsWith('#')) {
      return path;
    }
    return `${base}${path}`;
  }

  function isActive(path: string) {
    if (path === '/') {
      return activePath === 'dashboard';
    }
    return path.includes(activePath);
  }

  function statusDotClass(status: WorkspaceStatusState) {
    if (status === 'connected') return 'bg-emerald-500';
    if (status === 'running_disconnected') return 'bg-amber-500';
    return 'bg-red-500';
  }

  onMount(() => {
    prefs.initialize();
    liveStatus.start(prefs.selectedWorkspace);
    getAdminConfig()
      .then((payload) => {
        adminConfig = payload.data ?? DEFAULT_ADMIN_CONFIG;
      })
      .catch(() => {
        adminConfig = DEFAULT_ADMIN_CONFIG;
      });
  });
</script>

<svelte:head>
  <title>Hiro Admin</title>
</svelte:head>

<div
  class={cn(
    'grid min-h-screen lg:transition-[grid-template-columns] lg:duration-200',
    // Publish the sidebar width as a CSS custom property so position:fixed
    // descendants (e.g. the Knowledge Graph expanded view) can offset from the
    // content column instead of the viewport edge. Mobile (no sidebar) = 0.
    '[--admin-sidebar-w:0px]',
    prefs.sidebarCollapsed
      ? 'lg:grid-cols-[84px_minmax(0,1fr)] lg:[--admin-sidebar-w:84px]'
      : 'lg:grid-cols-[264px_minmax(0,1fr)] lg:[--admin-sidebar-w:264px]'
  )}
>
  <aside
    class="brand-surface sticky top-0 hidden h-screen min-w-0 flex-col border-r bg-card/95 p-3 text-card-foreground shadow-xl shadow-black/10 lg:flex"
    aria-label="Admin navigation"
  >
    <div class="flex min-h-12 items-center gap-3 px-2">
      <div
        class="grid size-10 shrink-0 place-items-center rounded-md border border-primary/25 bg-background/55 p-1 shadow-sm shadow-primary/20"
      >
        <img
          src={`${base}/images/logo-only2.png`}
          alt=""
          class="size-8 object-contain drop-shadow-sm"
          aria-hidden="true"
        />
      </div>
      {#if !prefs.sidebarCollapsed}
        <div class="min-w-0 font-sans">
          <strong class="brand-text-gradient block truncate text-sm">HiroLeague</strong>
          <span class="text-xs text-muted-foreground">Admin</span>
        </div>
      {/if}
    </div>

    <nav class="mt-5 grid gap-5 overflow-y-auto">
      {#each Object.entries(groups) as [group, items] (group)}
        <section class="grid gap-1" aria-label={group}>
          {#if !prefs.sidebarCollapsed}
            <div class="accent-text-gradient px-2 pb-1 font-sans text-[11px] font-bold uppercase tracking-wide">
              {group}
            </div>
          {/if}
          {#each items as item (item.path)}
            {@const Icon = iconMap[item.icon as keyof typeof iconMap] ?? Menu}
            <a
              class={cn(
                'flex min-h-10 items-center gap-3 rounded-md border border-transparent px-2 font-sans text-sm font-medium text-muted-foreground transition-colors hover:border-border hover:bg-secondary/35 hover:text-foreground',
                isActive(item.path) && 'border-primary/30 bg-primary/10 text-foreground shadow-sm shadow-primary/10',
                prefs.sidebarCollapsed && 'justify-center'
              )}
              href={navHref(item.path)}
              title={item.label}
            >
              <Icon size={18} />
              {#if !prefs.sidebarCollapsed}
                <span class="truncate">{item.label}</span>
              {/if}
            </a>
          {/each}
        </section>
      {/each}
    </nav>

    <div
      class={cn(
        'mt-auto flex items-center gap-3 rounded-md border bg-background/60 p-3',
        prefs.sidebarCollapsed && 'hidden'
      )}
    >
      {#if !prefs.sidebarCollapsed}
        <div class="min-w-0 font-sans text-xs">
          <strong class="block truncate text-sm">Workspace: {headerWorkspaceName}</strong>
          <span class="block truncate text-muted-foreground">
            Python: {adminConfig.python_version}
          </span>
          <span class="block truncate text-muted-foreground">
            Hiro: {adminConfig.hiro_package_version}
          </span>
        </div>
      {/if}
    </div>
  </aside>

  <div class="min-w-0">
    <header
      class={cn(
        'sticky top-0 z-20 flex min-h-16 items-center gap-3 border-b bg-background/85 backdrop-blur',
        ADMIN_SHELL_HEADER_PADDING
      )}
    >
      <Button
        class="hidden lg:inline-flex"
        aria-label={prefs.sidebarCollapsed ? 'Expand navigation' : 'Collapse navigation'}
        variant="outline"
        size="icon"
        onclick={prefs.toggleSidebar}
      >
        {#if prefs.sidebarCollapsed}
          <PanelLeftOpen size={17} />
        {:else}
          <PanelLeftClose size={17} />
        {/if}
      </Button>
      <Button class="lg:hidden" aria-label="Navigation" variant="outline" size="icon">
        <Menu size={17} />
      </Button>
      <img
        src={`${base}/images/logo-only2.png`}
        alt=""
        class="size-8 object-contain lg:hidden"
        aria-hidden="true"
      />
      <h1 class="accent-text-gradient min-w-0 truncate font-sans text-xl font-semibold">
        Control Room
      </h1>
      <span
        class={cn('size-2.5 shrink-0 rounded-full', statusDotClass(headerStatus))}
        title={headerStatusLabel}
        aria-label={headerStatusLabel}
      ></span>
      <div class="ml-auto flex items-center gap-2">
        <button
          type="button"
          class={cn(
            'relative inline-flex h-10 min-w-10 shrink-0 items-center justify-center rounded-lg border px-3 shadow-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
            chatOverlay.open
              ? 'border-primary bg-primary text-primary-foreground shadow-primary/30'
              : 'border-primary/50 bg-primary/15 text-primary shadow-primary/20 ring-1 ring-primary/25 hover:bg-primary/25 hover:text-primary hover:ring-primary/35'
          )}
          aria-pressed={chatOverlay.open}
          aria-label={chatOverlay.open ? 'Close chat overlay' : 'Open chat overlay'}
          title="Chat"
          onclick={() => chatOverlay.toggle()}
        >
          <MessagesSquare size={22} strokeWidth={2.25} aria-hidden="true" />
          <!-- Pulse when the agent is replying and the overlay is closed (unread affordance). -->
          {#if chatEngine.agentTyping && !chatOverlay.open}
            <span
              class="absolute -right-0.5 -top-0.5 size-2.5 animate-pulse rounded-full bg-emerald-500 ring-2 ring-background"
              aria-hidden="true"
            ></span>
          {/if}
        </button>
        <a
          class="inline-flex h-9 w-11 shrink-0 items-center justify-center gap-1 rounded-md border border-input bg-background text-muted-foreground shadow-xs transition-colors hover:bg-accent hover:text-accent-foreground"
          href={adminDocsUrl}
          target="_blank"
          rel="noreferrer"
          aria-label="Open Hiro docs in a new tab"
          title={`Open Hiro docs in a new tab: ${adminDocsUrl}`}
        >
          <BookOpen size={17} />
          <ExternalLink size={14} />
        </a>
        <Button
          aria-label={prefs.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          title={prefs.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          variant="outline"
          size="icon"
          onclick={prefs.toggleTheme}
        >
          {#if prefs.theme === 'dark'}
            <Sun size={17} />
          {:else}
            <Moon size={17} />
          {/if}
        </Button>
      </div>
    </header>

    <main class={cn(ADMIN_SHELL_CONTENT_PADDING, mainClass)}>
      {@render children?.()}
    </main>
  </div>
</div>

<!-- Global chat: floating overlay + the shared engine's toast/clear-messages modal.
     These live in the shell (not the /chats page) so they work over any page. -->
<GlobalChatOverlay />

<ToastHost toast={chatEngine.toast} />

<ChatChannelClearMessagesModal
  open={chatEngine.clearMessagesConfirmOpen}
  channelName={chatEngine.clearMessagesChannelDisplayName}
  busy={chatEngine.busy}
  onClose={() => chatEngine.closeClearMessagesModal()}
  onConfirm={() => void chatEngine.submitClearMessages()}
/>
