<script lang="ts">
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { ADMIN_SECTION_TITLE } from '$lib/styling/admin-tokens';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import { createWhatsAppController } from './state/whatsapp-controller.svelte';

  const toasts = createToastNotifier();
  const ctrl = createWhatsAppController(toasts.notify);

  $effect(() => {
    void ctrl.load();
  });
  $effect(() => ctrl.startPolling());
</script>

<AdminPageHeader kicker="Communication" title="WhatsApp" sticky>
  {#if ctrl.loading}
    <InlineLoading label="Loading WhatsApp…" />
  {:else if ctrl.error}
    <InlineDestructiveAlert message={ctrl.error} />
  {:else}
    <div class="flex flex-col gap-6">
      <SectionCard class="grid gap-3">
        <h2 class={ADMIN_SECTION_TITLE}>Connection</h2>
        <div class="flex items-center gap-2 text-sm">
          <span
            class="inline-flex h-2.5 w-2.5 rounded-full {ctrl.connected
              ? 'bg-emerald-500'
              : ctrl.needsRepair
                ? 'bg-red-500'
                : 'bg-amber-500'}"
          ></span>
          <span class="font-medium capitalize">{ctrl.status?.state ?? 'unknown'}</span>
          {#if ctrl.status?.account}
            <span class="text-muted-foreground">· {ctrl.status.account}</span>
          {/if}
        </div>

        {#if ctrl.needsRepair}
          <InlineDestructiveAlert message={ctrl.statusMessage} />
        {/if}

        {#if !ctrl.connected && ctrl.qrSvg}
          <p class="mt-4 text-sm text-muted-foreground">
            Open WhatsApp on your phone → <strong>Linked Devices</strong> → <strong>Link a device</strong>,
            then scan this code.
          </p>
          <div
            class="mt-3 w-56 max-w-full rounded-md bg-white p-3 [&_svg]:h-full [&_svg]:w-full"
          >
            {@html ctrl.qrSvg}
          </div>
        {:else if !ctrl.connected}
          <p class="mt-4 text-sm text-muted-foreground">
            Waiting for a pairing code… (the WhatsApp client refreshes it every ~20s)
          </p>
        {/if}

        <div class="mt-2 flex flex-wrap gap-2">
          {#if ctrl.enabled}
            <Button variant="secondary" size="sm" onclick={() => ctrl.reconnect()} disabled={ctrl.busy}>
              Reconnect
            </Button>
            <Button variant="outline" size="sm" onclick={() => ctrl.logout()} disabled={ctrl.busy}>
              Log out
            </Button>
            <Button
              variant="destructive-outline"
              size="sm"
              onclick={() => ctrl.disable()}
              disabled={ctrl.busy}
            >
              Disable
            </Button>
          {:else}
            <Button size="sm" onclick={() => ctrl.enable()} disabled={ctrl.busy}>Enable</Button>
          {/if}
        </div>
      </SectionCard>

      <SectionCard class="grid gap-3">
        <h2 class={ADMIN_SECTION_TITLE}>Settings</h2>
        <div class="flex flex-col gap-4">
          <FormField
            label="Owner number"
            hint="Your personal WhatsApp number. Messages from it route to the General chat with Hiro."
          >
            <input bind:value={ctrl.ownerNumber} placeholder="e.g. 201223504849" />
          </FormField>

          <FormField
            label="Allowed senders"
            hint="Comma-separated numbers permitted to message the agent. The owner is always allowed; everyone else is ignored (deny-all by default)."
          >
            <input bind:value={ctrl.allowedSenders} placeholder="201112223333, 201445556666" />
          </FormField>

          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" bind:checked={ctrl.sendReadReceipts} />
            Send read receipts (blue ticks)
          </label>

          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" bind:checked={ctrl.audioOut} />
            Reply with voice notes when the character speaks (TTS)
          </label>

          <div class="flex items-center gap-3">
            <Button onclick={() => ctrl.save()} disabled={ctrl.saving}>
              {ctrl.saving ? 'Saving…' : 'Save settings'}
            </Button>
            <span class="text-xs text-muted-foreground">Changes apply after a server restart.</span>
          </div>
        </div>
      </SectionCard>
    </div>
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
