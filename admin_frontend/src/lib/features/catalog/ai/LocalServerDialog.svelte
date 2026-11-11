<script lang="ts">
  /**
   * A local server's dialog (LM Studio / Ollama), opened from its Providers row (same shape as the
   * plan-tool dialog): status, its models with what is loaded (and what Hiro loaded, idle how long),
   * and its settings — address, minutes before an idle model Hiro loaded is unloaded, and for LM
   * Studio the context and batch Hiro loads models with. Save (`PUT`) then checks; Check checks now.
   */
  import { RefreshCw } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import { Input } from '$kit/components/ui/input/index.js';
  import Field from '$kit/ui/field.svelte';
  import { dateTime } from '$lib/format/time';
  import { cn } from '$lib/utils';
  import type { AiController } from './ai-controller.svelte';
  import { LOCAL_SERVER_IDS, LOCAL_SERVER_KIND_LABELS, serverStatus } from './ai-profile-rules';

  let { ai }: { ai: AiController } = $props();
  const uid = $props.id();

  const id = $derived(
    LOCAL_SERVER_IDS.find((k) => k === ai.dialogProviderId) ?? null
  );
  const server = $derived(id ? ai.serverFor(id) : undefined);
  const status = $derived(server ? serverStatus(server) : null);
  const usedBy = $derived(id ? ai.profilesOnProvider(id) : []);
  const checking = $derived(id ? ai.serverChecking(id) : false);
  const BADGE = { ok: 'success', warn: 'warning', off: 'secondary' } as const;
</script>

<Dialog.Root
  open={!!id}
  onOpenChange={(next) => {
    if (!next) ai.closeProviderDialog();
  }}
>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-lg">
    {#if id}
      <Dialog.Header>
        <Dialog.Title class="flex items-center gap-2">
          {LOCAL_SERVER_KIND_LABELS[id]}
          {#if status}<Badge variant={BADGE[status.tone]}>{status.word}</Badge>{/if}
        </Dialog.Title>
        <Dialog.Description>
          A model server on a PC in the home: free, and questions never leave the house. One address per kind.
        </Dialog.Description>
      </Dialog.Header>

      {#if server}
        <dl class="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
          <dt class="text-muted-foreground">Status</dt>
          <dd class={cn(status?.tone === 'warn' && 'text-warning')}>
            {server.state === 'up' ? 'Up' : (server.error ?? status?.word)}
          </dd>
          <dt class="text-muted-foreground">Checked</dt>
          <dd>{server.checked_at ? dateTime(server.checked_at) : '—'}</dd>
          <dt class="text-muted-foreground">Used by</dt>
          <dd class="text-muted-foreground">{usedBy.length ? usedBy.join(', ') : 'No profile'}</dd>
          <dt class="text-muted-foreground">Models</dt>
          <dd>
            {#if server.models.length}
              <ul class="grid gap-1">
                {#each server.models as m (m.id)}
                  <li class="flex flex-wrap items-center gap-1.5">
                    <span>{m.display_name || m.name}</span>
                    {#if m.vision}<Badge variant="secondary">pictures</Badge>{/if}
                    {#if m.loaded_by_core}
                      <Badge variant="success">
                        loaded by Hiro{m.idle_s != null ? `, idle ${Math.floor(m.idle_s / 60)} min` : ''}
                      </Badge>
                    {:else if m.loaded}
                      <Badge variant="success">loaded</Badge>
                    {/if}
                  </li>
                {/each}
              </ul>
            {:else}
              <span class="text-muted-foreground">None known yet: check the server.</span>
            {/if}
          </dd>
        </dl>
      {:else}
        <p class="text-sm text-muted-foreground">{ai.serversError ?? 'Checking the server…'}</p>
      {/if}

      <div class="grid gap-3">
        <Field label="Address" for="{uid}-address" hint={id === 'lm_studio' ? 'e.g. http://192.168.1.90:1234' : 'e.g. http://127.0.0.1:11434'}>
          <Input id="{uid}-address" bind:value={ai.serverDraft.baseUrl} placeholder="http://" />
        </Field>
        <div class="grid items-start gap-3 sm:grid-cols-3">
          <Field label="Unload idle after (min)" for="{uid}-unload" hint="Models Hiro loaded.">
            <Input id="{uid}-unload" type="number" min="1" max="1440" step="5" bind:value={ai.serverDraft.unloadIdleMin} />
          </Field>
          {#if id === 'lm_studio'}
            <Field label="Context" for="{uid}-context" hint="A profile's own context wins.">
              <Input id="{uid}-context" type="number" min="2048" max="262144" step="1024" bind:value={ai.serverDraft.context} />
            </Field>
            <Field label="Batch" for="{uid}-batch" hint="Pictures need 2048 or more.">
              <Input id="{uid}-batch" type="number" min="64" max="16384" step="256" bind:value={ai.serverDraft.batch} />
            </Field>
          {/if}
        </div>
      </div>

      <Dialog.Footer>
        <Button variant="outline" disabled={checking || ai.serverSaving} onclick={() => void ai.checkServer(id)}>
          <RefreshCw size={15} class={cn(checking && 'animate-spin')} />
          {checking ? 'Checking…' : 'Check'}
        </Button>
        <Button disabled={ai.serverSaving || !ai.serverDraft.baseUrl.trim()} onclick={() => void ai.saveServer(id)}>
          {ai.serverSaving ? 'Saving…' : 'Save'}
        </Button>
      </Dialog.Footer>
    {/if}
  </Dialog.Content>
</Dialog.Root>
