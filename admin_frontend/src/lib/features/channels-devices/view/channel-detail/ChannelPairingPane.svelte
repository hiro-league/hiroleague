<script lang="ts">
  // Capability-driven pairing pane (design §5.2/§5.5). Renders the right linking UI
  // from the channel's declared pairing kind — QR today; token/oauth are stubs that
  // point the user at the relevant setting until those channels exist.
  let {
    kind,
    connected,
    qrSvg
  }: {
    kind: string;
    connected: boolean;
    qrSvg: string;
  } = $props();
</script>

{#if connected}
  <!-- Linked — nothing to pair. -->
{:else if kind === 'qr'}
  {#if qrSvg}
    <p class="mt-4 text-sm text-muted-foreground">
      Open the channel's app on your phone → <strong>Linked devices</strong> →
      <strong>Link a device</strong>, then scan this code.
    </p>
    <div class="mt-3 w-56 max-w-full rounded-md bg-white p-3 [&_svg]:h-full [&_svg]:w-full">
      {@html qrSvg}
    </div>
  {:else}
    <p class="mt-4 text-sm text-muted-foreground">
      Waiting for a pairing code… (the code refreshes periodically)
    </p>
  {/if}
{:else if kind === 'token'}
  <p class="mt-4 text-sm text-muted-foreground">
    Enter this channel's access token in <strong>Settings</strong> below, then enable the channel.
  </p>
{/if}
