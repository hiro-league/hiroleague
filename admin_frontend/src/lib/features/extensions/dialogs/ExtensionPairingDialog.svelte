<script lang="ts">
  import { Check, Copy } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$lib/components/ui/dialog';
  import { dateTime } from '$lib/format/time';
  import type { ExtensionsController } from '../state/extensions-controller.svelte';

  let { ctrl }: { ctrl: ExtensionsController } = $props();
</script>

<Dialog.Root
  open={ctrl.pairing !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.closePairing();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Pair an extension</Dialog.Title>
    </Dialog.Header>
    {#if ctrl.pairing}
      <div class="grid justify-items-center gap-3 text-center">
        <p class="font-sans text-sm text-muted-foreground">Type both into the extension's settings.</p>
        <div class="grid gap-1">
          <span class="font-sans text-xs uppercase tracking-wide text-muted-foreground">Address</span>
          <span class="font-mono text-base font-semibold break-all">{ctrl.pairing.address}</span>
        </div>
        <div class="grid gap-1">
          <span class="font-sans text-xs uppercase tracking-wide text-muted-foreground">Code</span>
          <span class="font-mono text-5xl font-bold tracking-widest text-primary">{ctrl.pairing.code}</span>
        </div>
        <p class="font-sans text-sm text-muted-foreground">
          Works once, until {dateTime(ctrl.pairing.expires_at)}.
        </p>
      </div>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={() => void ctrl.copyPairing()}>
        {#if ctrl.copied}
          <Check class="text-emerald-500" size={15} />
        {:else}
          <Copy size={15} />
        {/if}
        Copy address and code
      </Button>
      <Button onclick={() => ctrl.closePairing()}>Done</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
