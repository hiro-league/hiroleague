<script lang="ts">
  import { Button } from '$kit/components/ui/button/index.js';
  import Field from '$kit/ui/field.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import { Input } from '$kit/components/ui/input/index.js';
  import Notice from '$kit/ui/notice.svelte';
  import type { ExtensionsController } from '../state/extensions-controller.svelte';

  let { ctrl }: { ctrl: ExtensionsController } = $props();
  const uid = $props.id();

  const listen = $derived(ctrl.listen);
  // The running server still listens on the old address until it restarts.
  const restartPending = $derived(
    listen !== null && listen.live_host !== null && listen.live_host !== listen.host
  );
</script>

<!-- What the address is for sits in the field's tooltip, not on the page. -->
<Panel title="Where extensions connect" contentClass="grid gap-4">
  {#if listen}
    <div class="grid gap-1 font-sans text-sm">
      <span>Address to type in: <span class="font-mono font-semibold">{listen.address}</span></span>
      {#if listen.listening === true}
        <span class="text-xs text-muted-foreground">Listening on {listen.live_host}:{listen.port}.</span>
      {/if}
    </div>
    {#if listen.error}
      <Notice
        title="Extensions can't connect"
        message="The server couldn't listen on {listen.live_host}:{listen.port}: {listen.error}"
      />
    {/if}
    {#if restartPending}
      <Notice tone="warning" message="Restart the server for the new address to take effect." />
    {/if}
    {#if listen.note}
      <Notice tone="warning" title="Not encrypted" message={listen.note} />
    {/if}
  {/if}

  <form
    class="flex flex-col gap-3 md:flex-row md:items-end"
    onsubmit={(event) => {
      event.preventDefault();
      void ctrl.saveAddress();
    }}
  >
    <Field
      label="Listen address"
      for="{uid}-host"
      class="md:w-72"
      help="Where the core waits for apps to connect. 127.0.0.1 reaches only apps on this machine. For an app in a Docker network or on another machine, use the Docker bridge or LAN address, then restart the server."
    >
      <Input id="{uid}-host" bind:value={ctrl.host.value} placeholder="127.0.0.1" spellcheck="false" />
    </Field>
    <Button type="submit" variant="outline" disabled={ctrl.busy || !ctrl.host.dirty}>
      Save
    </Button>
  </form>
</Panel>
