<script lang="ts">
  // Install a channel: pick one of the channels not installed yet; it joins the list switched off.
  import { Download } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import Feedback from '$kit/ui/feedback.svelte';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import type { ExtensionsController } from '../state/extensions-controller.svelte';

  let { ctrl }: { ctrl: ExtensionsController } = $props();

  let chosen = $state('');
  const channels = $derived(ctrl.available.data ?? []);
  // The first channel is picked when the list arrives, or when the one picked is gone.
  const pick = $derived(channels.some((c) => c.name === chosen) ? chosen : (channels[0]?.name ?? ''));
  const description = $derived(channels.find((c) => c.name === pick)?.description ?? '');
</script>

<Dialog.Root
  open={ctrl.installOpen}
  onOpenChange={(next) => {
    if (!next) ctrl.closeInstall();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Install a channel</Dialog.Title>
      <Dialog.Description>It joins the list switched off: switch it on, then open its Settings.</Dialog.Description>
    </Dialog.Header>
    {#if ctrl.available.data === null && !ctrl.available.error}
      <p class="text-sm text-muted-foreground">Reading the channels…</p>
    {:else if ctrl.available.error}
      <Feedback error={ctrl.available.error} />
    {:else if channels.length === 0}
      <p class="text-sm text-muted-foreground">Every channel Hiro knows is installed.</p>
    {:else}
      <div class="grid gap-2">
        <PickSelect
          class="h-9 w-full text-sm"
          value={pick}
          onchange={(v) => (chosen = v)}
          options={channels.map((c) => ({ value: c.name, label: c.label }))}
          label="Channel to install"
          disabled={ctrl.installAction.busy}
        />
        {#if description}<p class="text-xs text-muted-foreground">{description}</p>{/if}
        {#if ctrl.installAction.busy}
          <p class="text-xs text-muted-foreground">
            Installing; the first time can take a few minutes while its parts download.
          </p>
        {/if}
        <Feedback action={ctrl.installAction} />
      </div>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" disabled={ctrl.installAction.busy} onclick={() => ctrl.closeInstall()}>Cancel</Button>
      <Button disabled={!pick || ctrl.installAction.busy} onclick={() => void ctrl.install(pick)}>
        <Download size={15} /> {ctrl.installAction.busy ? 'Installing…' : 'Install'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
