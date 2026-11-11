<script lang="ts">
  /**
   * HiroLeague's sign-in (Phase 6): a name and a password, checked on this machine, so it works on any
   * address and without internet. Shown instead of the whole admin until someone signs in.
   *
   * Phase 8: one sign-in for HiroLeague and its apps. An app's site (HomeHiro) sends people here with
   * ?for=<app>&next=<path>; once signed in they go back there. A connected extension may offer another
   * way in ("Sign in with Home Assistant"): its button starts that sign-in on the extension's side.
   * ?signin_error= says why the last try didn't work.
   */
  import { base } from '$app/paths';
  import { Action } from '$kit/state/action.svelte';
  import { page } from '$app/state';
  import { House, LogIn, TriangleAlert } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import Field from '$kit/ui/field.svelte';
  import { Input } from '$kit/components/ui/input/index.js';
  import { backToAppUrl, offeredSignInUrl } from '$lib/api/auth';
  import { adminSession } from '$lib/runtime/admin-session.svelte';

  const uid = $props.id();
  let name = $state('');
  let password = $state('');
  const signing = new Action();
  let error = $state<string | null>(null);

  const forApp = $derived(page.url.searchParams.get('for'));
  const next = $derived(page.url.searchParams.get('next'));
  const failed = $derived(page.url.searchParams.get('signin_error'));
  // The app's own name isn't known before signing in; "home" reads well enough capitalised.
  const appName = $derived(forApp ? forApp.charAt(0).toUpperCase() + forApp.slice(1) : null);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (!name.trim() || !password) return;
    const refused = await signing.run(() => adminSession.signIn(name.trim(), password));
    error = refused || signing.error || null;
    if (error) {
      password = '';
    } else if (forApp) {
      window.location.assign(backToAppUrl(forApp, next));
    }
  }
</script>

<div class="grid min-h-screen place-items-center bg-background px-4">
  <div class="grid w-full max-w-sm gap-6 rounded-xl border bg-card p-8 shadow-sm">
    <div class="grid justify-items-center gap-2 text-center">
      <img src={`${base}/images/logo-only2.png`} alt="" class="size-12 object-contain" aria-hidden="true" />
      <h1 class="accent-text-gradient font-sans text-2xl font-semibold">HiroLeague</h1>
      {#if appName}
        <p class="flex items-center gap-1.5 text-sm text-muted-foreground">
          <House size={14} /> Sign in to open <strong class="text-foreground">{appName}</strong>
        </p>
      {:else}
        <p class="text-sm text-muted-foreground">Sign in to the Control Room</p>
      {/if}
    </div>

    {#if failed}
      <p class="flex gap-2 text-sm text-destructive" role="alert">
        <TriangleAlert size={16} class="mt-0.5 shrink-0" />{failed}
      </p>
    {/if}

    {#if !adminSession.anyoneSignsIn}
      <div class="grid gap-2 rounded-lg border border-warning/30 bg-warning/5 p-4 text-sm">
        <p class="font-semibold">Nobody can sign in yet.</p>
        <p class="text-muted-foreground">On the computer that runs Hiro, set the owner's sign-in:</p>
        <code class="rounded bg-muted px-2 py-1 font-mono text-xs">hiro people owner</code>
      </div>
    {:else}
      {#if adminSession.offers.length}
        <div class="grid gap-2">
          {#each adminSession.offers as offer (offer.id)}
            <Button
              variant="outline"
              onclick={() => window.location.assign(offeredSignInUrl(offer.id, forApp, next))}
              title="You log in on {offer.label}'s own page, then come back here"
            >
              <LogIn size={15} /> Sign in with {offer.label}
            </Button>
          {/each}
        </div>
        <div class="flex items-center gap-3 text-xs text-muted-foreground">
          <span class="h-px flex-1 bg-border"></span> or <span class="h-px flex-1 bg-border"></span>
        </div>
      {/if}
      <form class="grid gap-4" onsubmit={submit}>
        <Field label="Name" for="{uid}-name">
          <Input id="{uid}-name" bind:value={name} autocomplete="username" autocapitalize="none" spellcheck={false} required />
        </Field>
        <Field label="Password" for="{uid}-password">
          <Input id="{uid}-password" bind:value={password} type="password" autocomplete="current-password" required />
        </Field>
        {#if error}
          <p class="text-sm text-destructive" role="alert">{error}</p>
        {/if}
        <Button type="submit" disabled={signing.busy || !name.trim() || !password}>
          <LogIn size={15} /> Sign in
        </Button>
      </form>
      <p class="text-center text-xs text-muted-foreground">
        {#if appName}
          You stay signed in to HiroLeague and {appName} for 90 days on this browser.
        {:else}
          Forgot it? On the computer that runs Hiro: <code class="font-mono">hiro people sign-in</code>
        {/if}
      </p>
    {/if}
  </div>
</div>
