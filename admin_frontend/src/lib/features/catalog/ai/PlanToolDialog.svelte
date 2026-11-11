<script lang="ts">
  /**
   * A plan tool's dialog ("Claude Code" / "Codex"), opened from its Providers row: sign-in state and
   * plan, when the sign-in ends, version and last update, the queue rule, and Sign in / Sign in again
   * / Sign out, Update now, Test question. Sign-in: Claude Code shows a link, then takes the code its
   * page shows; Codex shows a link and a code to type there; both are polled until done.
   */
  import { ExternalLink, LogIn, LogOut, MessageSquare, RefreshCw, X } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$lib/components/ui/dialog';
  import { dateTime } from '$lib/format/time';
  import { ADMIN_INPUT } from '$lib/styling/admin-tokens';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineWarningAlert from '$lib/ui/InlineWarningAlert.svelte';
  import { cn } from '$lib/utils';
  import type { AiController } from './ai-controller.svelte';
  import { planAccountWords, planToolStatus, signInExpiryWords } from './ai-profile-rules';

  let { ai }: { ai: AiController } = $props();

  const tool = $derived(ai.plans.find((t) => t.id === ai.dialogProviderId));
  const status = $derived(tool ? planToolStatus(tool) : null);
  const busy = $derived(tool ? ai.planBusy[tool.id] : '');
  const usedBy = $derived(tool ? ai.profilesOnProvider(tool.id) : []);
  const signIn = $derived(tool ? ai.signIns[tool.id] : null);
  const test = $derived(tool ? ai.planTests[tool.id] : null);
  const updating = $derived(!!ai.planUpdates?.running);
  const BADGE = { ok: 'success', warn: 'warning', off: 'secondary' } as const;
</script>

<Dialog.Root
  open={!!tool}
  onOpenChange={(next) => {
    if (!next) ai.closeProviderDialog();
  }}
>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-lg">
    {#if tool && status}
      <Dialog.Header>
        <Dialog.Title class="flex items-center gap-2">
          {tool.name}
          <Badge variant={BADGE[status.tone]}>{status.word}</Badge>
        </Dialog.Title>
        <Dialog.Description>
          Signed in with your own plan: what Hiro asks counts against that plan's limits, shared with your own use of it.
        </Dialog.Description>
      </Dialog.Header>

      {#if tool.problem}
        <InlineWarningAlert message={tool.problem} />
      {/if}

      <dl class="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
        <dt class="text-muted-foreground">Plan</dt>
        <dd>{planAccountWords(tool) ?? '—'}</dd>
        <dt class="text-muted-foreground">Sign-in</dt>
        <dd class={cn(status.tone === 'warn' && 'text-amber-700 dark:text-amber-300')}>{signInExpiryWords(tool)}</dd>
        <dt class="text-muted-foreground">Version</dt>
        <dd class="font-mono text-xs leading-5">{tool.version ?? '—'}</dd>
        <dt class="text-muted-foreground">Last update</dt>
        <dd>
          {ai.planUpdates?.last_run ? dateTime(ai.planUpdates.last_run) : 'Never'}
          {#if updating}<span class="text-muted-foreground">· updating now…</span>{/if}
        </dd>
        {#if ai.planUpdates?.message && !updating}
          <dt class="text-muted-foreground">Update said</dt>
          <dd class={cn('text-xs', ai.planUpdates.ok === false ? 'text-destructive' : 'text-muted-foreground')}>
            {ai.planUpdates.message}
          </dd>
        {/if}
        <dt class="text-muted-foreground">Queue</dt>
        <dd class="text-muted-foreground">{tool.queue_note}</dd>
        <dt class="text-muted-foreground">Models</dt>
        <dd class="text-muted-foreground">
          {tool.models.length ? tool.models.map((m) => m.name).join(', ') : (tool.models_problem ?? 'None listed')}
        </dd>
        <dt class="text-muted-foreground">Used by</dt>
        <dd class="text-muted-foreground">{usedBy.length ? usedBy.join(', ') : 'No profile'}</dd>
      </dl>

      {#if signIn}
        <div class="grid gap-2 rounded-md border p-3 text-sm">
          {#if signIn.state === 'waiting'}
            {#if signIn.link}
              <a class="inline-flex w-fit items-center gap-1 text-primary underline" href={signIn.link} target="_blank" rel="noopener noreferrer">
                Open the {tool.name} sign-in page <ExternalLink size={13} />
              </a>
            {:else}
              <p class="text-muted-foreground">Starting {tool.name}'s sign-in…</p>
            {/if}
            {#if signIn.code}
              <p>Type this code on that page:</p>
              <p class="font-mono text-2xl tracking-widest">{signIn.code}</p>
              <p class="text-xs text-muted-foreground">Waiting for you… this turns to signed in by itself.</p>
            {:else if signIn.takes_code}
              <p>Approve with your account; the page then shows a code. Paste it here:</p>
              <form
                class="flex gap-2"
                onsubmit={(event) => {
                  event.preventDefault();
                  void ai.sendSignInCode(tool.id);
                }}
              >
                <input
                  class={cn(ADMIN_INPUT, 'min-w-0 flex-1')}
                  bind:value={ai.signInCodes[tool.id]}
                  placeholder="Code from {tool.name}"
                  autocomplete="off"
                  aria-label="Code from {tool.name}"
                />
                <Button type="submit" disabled={!!busy || !(ai.signInCodes[tool.id] ?? '').trim()}>Send</Button>
              </form>
              {#if signIn.code_sent}
                <p class="text-xs text-muted-foreground">Code sent; waiting for {tool.name}…</p>
              {/if}
            {/if}
          {:else if signIn.state === 'blocked' || signIn.state === 'failed' || signIn.state === 'expired'}
            <InlineDestructiveAlert message={signIn.message ?? `The sign-in ${signIn.state === 'expired' ? 'expired' : 'stopped'}.`} />
          {/if}
          <Button size="sm" variant="ghost" class="w-fit" onclick={() => void ai.cancelSignIn(tool.id)}>
            <X size={13} />
            {signIn.state === 'waiting' ? 'Cancel the sign-in' : 'Close'}
          </Button>
        </div>
      {/if}

      {#if test}
        {#if test.ok}
          <p class="rounded-md bg-muted px-3 py-2 text-sm">
            "{test.answer}"
            <span class="text-xs text-muted-foreground">· {test.model ?? 'model not said'} · {(test.ms / 1000).toFixed(1)} s</span>
          </p>
        {:else}
          <InlineDestructiveAlert message={test.error ?? 'The test question failed.'} />
        {/if}
      {/if}
      {#if busy}
        <p class="text-xs text-muted-foreground">{busy}</p>
      {/if}

      <Dialog.Footer class="flex-wrap gap-2">
        {#if tool.installed && tool.signed_in}
          <Button variant="outline" disabled={!!busy} onclick={() => void ai.testQuestion(tool.id)}>
            <MessageSquare size={15} /> Test question
          </Button>
        {/if}
        <Button variant="outline" disabled={updating} onclick={() => void ai.updateNow()}>
          <RefreshCw size={15} class={cn(updating && 'animate-spin')} />
          {tool.installed ? 'Update now' : 'Install'}
        </Button>
        {#if tool.installed && (!tool.signed_in || tool.attention) && signIn?.state !== 'waiting'}
          <Button disabled={!!busy} onclick={() => void ai.signIn(tool.id)}>
            <LogIn size={15} />
            {tool.signed_in ? 'Sign in again' : 'Sign in'}
          </Button>
        {/if}
        {#if tool.signed_in}
          <Button variant="destructive" disabled={!!busy} onclick={() => void ai.signOut(tool.id)}>
            <LogOut size={15} /> Sign out
          </Button>
        {/if}
      </Dialog.Footer>
    {/if}
  </Dialog.Content>
</Dialog.Root>
