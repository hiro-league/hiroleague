<script lang="ts">
  import { Check, Copy, Link2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { DevicesController } from '../state/devices-controller.svelte';
  import { formatDeviceTimestamp } from '../shared/channels-devices-format';
  import { sanitizePairingQrSvg } from '../shared/sanitize-pairing-qr-svg';

  type Props = {
    ctrl: DevicesController;
  };

  let { ctrl }: Props = $props();

  const qrSvg = $derived(ctrl.pairing ? sanitizePairingQrSvg(ctrl.pairing.qr_svg) : '');
</script>

<Dialog.Root
  open={ctrl.pairing !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.closePairing();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Pairing code</Dialog.Title>
    </Dialog.Header>
    {#if ctrl.pairing}
      <div class="grid justify-items-center gap-3 text-center">
        <div
          role="img"
          aria-label="Device pairing QR code"
          class="grid size-48 place-items-center rounded-md border bg-white p-2 text-black [&_svg]:h-full [&_svg]:w-full"
        >
          {@html qrSvg}
        </div>
        <div class="font-mono text-5xl font-bold tracking-widest text-primary">{ctrl.pairing.code}</div>
        <p class="font-sans text-sm text-muted-foreground">
          Expires: {formatDeviceTimestamp(ctrl.pairing.expires_at)}
        </p>
        <p class="font-sans text-sm text-muted-foreground">
          Scan the QR code or enter the code manually in the mobile app.
        </p>
        <div class="flex max-w-full items-center gap-1 font-mono text-xs text-muted-foreground">
          <Link2 size={13} />
          <span class="truncate">{ctrl.pairing.gateway_url || 'no gateway configured'}</span>
        </div>
      </div>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={() => void ctrl.copyPairingPayload()}>
        {#if ctrl.copied}
          <Check class="text-emerald-500" size={15} />
        {:else}
          <Copy size={15} />
        {/if}
        Copy pairing message
      </Button>
      <Button onclick={() => ctrl.closePairing()}>Close</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
