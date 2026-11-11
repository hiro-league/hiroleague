<script lang="ts">
  /**
   * What someone sees when their role doesn't open HiroLeague's settings (Phase 8; Adult and Kid by
   * default): no menu and no settings, only their apps and Sign out. The API refuses everything else
   * for them anyway (RequireSignIn).
   */
  import { base } from '$app/paths';
  import { LogOut } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import { adminSession } from '$lib/runtime/admin-session.svelte';
  import AppsCard from './AppsCard.svelte';

  const name = $derived(adminSession.person?.name ?? '');
</script>

<div class="grid min-h-screen content-start bg-background">
  <header class="flex items-center justify-between gap-3 border-b px-4 py-4 sm:px-6">
    <span class="flex items-center gap-3">
      <img src={`${base}/images/logo-only2.png`} alt="" class="size-8 object-contain" aria-hidden="true" />
      <strong class="accent-text-gradient font-sans text-lg font-semibold">HiroLeague</strong>
    </span>
    <span class="flex items-center gap-3 font-sans text-sm">
      <span class="hidden text-muted-foreground sm:inline">
        {name}{adminSession.roleName ? ` · ${adminSession.roleName}` : ''}
      </span>
      <Button variant="outline" size="sm" onclick={() => void adminSession.signOut()}>
        <LogOut size={14} /> Sign out
      </Button>
    </span>
  </header>
  <main class="mx-auto grid w-full max-w-4xl content-start gap-5 px-4 py-8 sm:px-6">
    <div class="grid gap-1">
      <h1 class="font-sans text-2xl font-semibold">Hi {name}</h1>
      <p class="font-sans text-sm text-muted-foreground">Your apps. HiroLeague's settings aren't part of your role.</p>
    </div>
    <AppsCard />
  </main>
</div>
