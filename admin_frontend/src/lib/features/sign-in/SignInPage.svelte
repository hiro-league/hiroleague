<script lang="ts">
  /**
   * HiroLeague's own admin sign-in (Phase 6): a name and a password, checked on this
   * machine, so it works on any address and without internet. Shown instead of the
   * whole admin until someone signs in.
   */
  import { base } from '$app/paths';
  import { LogIn } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { Input } from '$lib/components/ui/input';
  import { adminSession } from '$lib/runtime/admin-session.svelte';

  let name = $state('');
  let password = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (!name.trim() || !password) return;
    busy = true;
    error = await adminSession.signIn(name.trim(), password);
    busy = false;
    if (error) password = '';
  }
</script>

<div class="grid min-h-screen place-items-center bg-background px-4">
  <div class="grid w-full max-w-sm gap-6 rounded-xl border bg-card p-8 shadow-sm">
    <div class="grid justify-items-center gap-2 text-center">
      <img src={`${base}/images/logo-only2.png`} alt="" class="size-12 object-contain" aria-hidden="true" />
      <h1 class="accent-text-gradient font-sans text-2xl font-semibold">HiroLeague</h1>
      <p class="text-sm text-muted-foreground">Sign in to the Control Room</p>
    </div>

    {#if !adminSession.anyoneSignsIn}
      <div class="grid gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
        <p class="font-semibold">Nobody can sign in yet.</p>
        <p class="text-muted-foreground">On the computer that runs Hiro, set the owner's sign-in:</p>
        <code class="rounded bg-muted px-2 py-1 font-mono text-xs">hiro people owner</code>
      </div>
    {:else}
      <form class="grid gap-4" onsubmit={submit}>
        <FormField label="Name">
          <Input bind:value={name} autocomplete="username" autocapitalize="none" spellcheck={false} required />
        </FormField>
        <FormField label="Password">
          <Input bind:value={password} type="password" autocomplete="current-password" required />
        </FormField>
        {#if error}
          <p class="text-sm text-destructive" role="alert">{error}</p>
        {/if}
        <Button type="submit" disabled={busy || !name.trim() || !password}>
          <LogIn size={15} /> Sign in
        </Button>
      </form>
      <p class="text-center text-xs text-muted-foreground">
        Forgot it? On the computer that runs Hiro: <code class="font-mono">hiro people sign-in</code>
      </p>
    {/if}
  </div>
</div>
