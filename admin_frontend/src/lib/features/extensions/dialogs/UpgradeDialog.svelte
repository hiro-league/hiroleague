<script lang="ts">
  // Upgrading an installed app from the newer package in the Hiro home's packages folder (Installing apps): a job of
  // the core. Its steps are the core's own, followed by the install's step in the list; then where it ended.
  import { ArrowUpCircle } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import type { Installs } from '../state/installs.svelte';

  let { inst }: { inst: Installs } = $props();

  const up = $derived(inst.upgrade);
  const steps = $derived(up?.state?.steps ?? []);
  const info = $derived(up ? inst.installOf(up.row) : null);
  // The step reached: the install's own while it upgrades; every one done once it ended upgraded
  const at = $derived(info?.state === 'upgrading' ? steps.indexOf(info.step) : -1);
  const running = $derived(!!up?.state?.running);
  const ended = $derived(!!up?.state && !up.state.running);
  const tone = $derived(up?.state?.outcome === 'upgraded' ? 'text-success' : up?.state?.outcome === 'stayed' ? 'text-warning' : 'text-destructive');
</script>

<Dialog.Root
  open={up !== null}
  onOpenChange={(next) => {
    if (!next) inst.closeUpgrade();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Upgrade {up?.row.label} to {up?.offer.version}</Dialog.Title>
    </Dialog.Header>
    {#if up}
      {#if up.state}
        <ol class="grid gap-2 font-sans text-sm">
          {#each steps as step, i (step)}
            {@const done = (ended && up.state.outcome === 'upgraded') || (at >= 0 && i < at)}
            <li class="flex items-center gap-2">
              <StatusDot tone={done ? 'ok' : running && i === at ? 'info' : 'neutral'} pulse={running && i === at} />
              <span class={done || (running && i === at) ? '' : 'text-muted-foreground'}>
                {step.charAt(0).toUpperCase() + step.slice(1)}
              </span>
            </li>
          {/each}
        </ol>
      {:else}
        <p class="font-sans text-sm text-muted-foreground">
          {up.row.label} {info?.version} → {up.offer.version}, from {up.offer.file}. Its data is copied and the new
          migrations tried on a copy first; when the new version doesn't answer, it goes back by itself.
        </p>
      {/if}
      {#if ended}
        <p class="font-sans text-sm {tone}">{up.state?.words}</p>
        {#if up.state?.new_asks.length}
          <p class="font-sans text-xs text-muted-foreground">
            It asks for more, which waits for your yes on its Permissions: {up.state.new_asks.join('; ')}.
          </p>
        {/if}
      {/if}
      {#if up.error}<p class="font-sans text-sm text-destructive">{up.error}</p>{/if}
    {/if}
    <Dialog.Footer>
      {#if up && !up.state}
        <Button variant="outline" onclick={() => inst.closeUpgrade()}>Cancel</Button>
        <Button onclick={() => void inst.runUpgrade()}><ArrowUpCircle size={15} /> Upgrade</Button>
      {:else}
        <Button disabled={running} onclick={() => inst.closeUpgrade()}>Done</Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
