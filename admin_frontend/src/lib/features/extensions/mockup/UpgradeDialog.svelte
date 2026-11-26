<script lang="ts">
  // mockup (Installing apps, phase 5, task 6): upgrading an installed app from the newer package in the Hiro home's
  // packages folder. Its steps are the ones the core records; here they only walk by.
  import { ArrowUpCircle } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import MockupBadge from '$kit/ui/mockup-badge.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import { UPGRADE_STEPS } from './installed';
  import type { InstallsMock } from './installs-mock.svelte';

  let { mock, titleOf }: { mock: InstallsMock; titleOf: (name: string) => string } = $props();

  const up = $derived(mock.upgrade);
  const from = $derived(up ? (mock.byKey(up.key)?.previous ?? '') : '');
</script>

<Dialog.Root
  open={up !== null}
  onOpenChange={(next) => {
    if (!next) mock.closeUpgrade();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2">
        Upgrade {up ? titleOf(up.key) : ''} to {up?.to}
        <MockupBadge />
      </Dialog.Title>
    </Dialog.Header>
    {#if up}
      <ol class="grid gap-2 font-sans text-sm">
        {#each UPGRADE_STEPS as step, i (step)}
          <li class="flex items-center gap-2">
            <StatusDot
              tone={up.done || i < up.step ? 'ok' : i === up.step ? 'info' : 'neutral'}
              pulse={!up.done && i === up.step}
            />
            <span class={i > up.step && !up.done ? 'text-muted-foreground' : ''}>{step}</span>
          </li>
        {/each}
      </ol>
      {#if up.done}
        <p class="font-sans text-sm text-success">{titleOf(up.key)} runs {up.to} (from {from}).</p>
      {/if}
    {/if}
    <Dialog.Footer>
      {#if up && up.step < 0}
        <Button variant="outline" onclick={() => mock.closeUpgrade()}>Cancel</Button>
        <Button onclick={() => mock.startUpgrade()}><ArrowUpCircle size={15} /> Upgrade</Button>
      {:else}
        <Button disabled={!up?.done} onclick={() => mock.closeUpgrade()}>Done</Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
