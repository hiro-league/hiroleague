<script lang="ts">
  import { base } from '$app/paths';
  import {
    Activity,
    BookOpen,
    Cpu,
    Grid2X2,
    KeyRound,
    List,
    Menu,
    PanelLeftClose,
    PanelLeftOpen,
    Server,
    User
  } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import type { Snippet } from 'svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { createShellPreferences } from '$lib/preferences/shell-preferences.svelte';
  import { cn } from '$lib/utils';
  import { navItems } from './nav';

  let { activePath = 'dashboard', children }: { activePath?: string; children?: Snippet } =
    $props();
  const prefs = createShellPreferences();

  const groups = $derived(
    navItems.reduce<Record<string, typeof navItems>>((acc, item) => {
      acc[item.group] = [...(acc[item.group] ?? []), item];
      return acc;
    }, {})
  );

  const iconMap = {
    activity: Activity,
    book: BookOpen,
    cpu: Cpu,
    grid: Grid2X2,
    key: KeyRound,
    list: List,
    server: Server,
    user: User
  };

  const niceguiHome = $derived(
    location.port === '5173'
      ? `${import.meta.env.VITE_HIRO_ADMIN_ORIGIN ?? 'http://127.0.0.1:18083'}/`
      : '/'
  );

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

  onMount(() => {
    prefs.initialize();
  });
</script>

<svelte:head>
  <title>Hiro Admin Next</title>
</svelte:head>

<div
  class={cn(
    'grid min-h-screen lg:transition-[grid-template-columns] lg:duration-200',
    prefs.sidebarCollapsed
      ? 'lg:grid-cols-[84px_minmax(0,1fr)]'
      : 'lg:grid-cols-[264px_minmax(0,1fr)]'
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
          <span class="text-xs text-muted-foreground">Admin Next</span>
        </div>
      {/if}
    </div>

    <nav class="mt-5 grid gap-5 overflow-y-auto">
      {#each Object.entries(groups) as [group, items]}
        <section class="grid gap-1" aria-label={group}>
          {#if !prefs.sidebarCollapsed}
            <div class="px-2 pb-1 font-sans text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
              {group}
            </div>
          {/if}
          {#each items as item}
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
        prefs.sidebarCollapsed && 'justify-center px-2'
      )}
    >
      <span class="size-2.5 shrink-0 rounded-full bg-brand"></span>
      {#if !prefs.sidebarCollapsed}
        <div class="min-w-0 font-sans">
          <strong class="block truncate text-sm">{prefs.selectedWorkspace ?? 'local-dev'}</strong>
          <span class="text-xs text-muted-foreground">Selected workspace</span>
        </div>
      {/if}
    </div>
  </aside>

  <div class="min-w-0">
    <header
      class="sticky top-0 z-20 flex min-h-16 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur md:px-6"
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
        Hiro League Control Room
      </h1>
      <div class="ml-auto hidden items-center gap-2 md:flex">
        <a
          class="inline-flex h-8 items-center justify-center rounded-md border border-input bg-background px-3 font-sans text-xs font-semibold shadow-xs transition-colors hover:bg-accent hover:text-accent-foreground"
          href={niceguiHome}
        >
          NiceGUI Home
        </a>
      </div>
    </header>

    <main class="p-4 md:p-6">
      {@render children?.()}
    </main>
  </div>
</div>
