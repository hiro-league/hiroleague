<script lang="ts">
  import { errorMessage } from '$kit/api/client';
  /**
   * The dashboard's Apps card (Phase 8): each extension's own site, as it declared it when it connected
   * (title, icon, address, the roles that see it). A tile opens the site in a new tab, where the same
   * sign-in lets you in. Nothing shows when no extension declares a site.
   */
  import { onMount } from 'svelte';
  import { AppWindow, ChartColumn, ExternalLink, House } from '@lucide/svelte';
  import Panel from '$kit/ui/panel.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import { listApps, type AppSite } from '$lib/api/auth';

  // The icons extensions may name (offers.shows "icon"); anything else gets a plain app icon.
  const ICONS = { house: House, chart: ChartColumn } as const; // chart: the code reports

  let apps = $state<AppSite[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      apps = (await listApps()).apps;
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loaded = true;
    }
  });

  const iconFor = (name: string) => ICONS[name as keyof typeof ICONS] ?? AppWindow;
</script>

{#if error}
  <Notice message={error} class="text-xs" />
{:else if loaded && apps.length}
  <Panel class="grid gap-4">
    <div class="flex items-baseline justify-between gap-3">
      <h2 class="font-sans text-base font-semibold">Apps</h2>
      <span class="font-sans text-xs text-muted-foreground">Open in a new tab; the same sign-in lets you in</span>
    </div>
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {#each apps as app (app.extension)}
        {@const Icon = iconFor(app.icon)}
        <a
          href={app.url}
          target="_blank"
          rel="noopener"
          class="group grid gap-2 rounded-lg border bg-background p-4 transition-colors hover:border-primary/50 hover:bg-primary/5"
          title={app.online ? `Open ${app.title} in a new tab` : `${app.title} isn't connected to HiroLeague right now`}
        >
          <div class="flex items-center justify-between">
            <span class="grid size-10 place-items-center rounded-lg bg-primary/10 text-primary">
              <Icon size={20} />
            </span>
            <ExternalLink size={14} class="text-muted-foreground group-hover:text-primary" />
          </div>
          <strong class="font-sans text-sm font-semibold">{app.title}</strong>
          <span class="flex items-center gap-1.5 font-sans text-xs text-muted-foreground">
            <StatusDot tone={app.online ? 'ok' : 'off'} />
            {app.online ? 'Online' : 'Offline'} · {app.url.replace(/^https?:\/\//, '')}
          </span>
        </a>
      {/each}
    </div>
  </Panel>
{/if}
