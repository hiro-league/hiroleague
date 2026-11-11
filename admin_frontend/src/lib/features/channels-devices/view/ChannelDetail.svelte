<script lang="ts">
  import { untrack } from 'svelte';
  import { ArrowLeft } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import Panel from '$kit/ui/panel.svelte';
  import Loading from '$kit/ui/loading.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import ConfirmDialog from '$kit/ui/confirm-dialog.svelte';
  import type { Notify } from '$kit/ui/toast.svelte';
  import { createChannelDetailController } from '../state/channel-detail-controller.svelte';
  import ChannelConnectionCard from './channel-detail/ChannelConnectionCard.svelte';
  import SchemaConfigForm from './channel-detail/SchemaConfigForm.svelte';

  let {
    name,
    notify,
    onBack,
    onChanged
  }: {
    name: string;
    notify: Notify;
    onBack: () => void;
    onChanged: () => void;
  } = $props();

  // Keyed by name at the call site ({#key}), so this component — and its controller —
  // is rebuilt per channel; capturing the props once (untrack) is intentional.
  const ctrl = untrack(() => createChannelDetailController(name, notify, onChanged));

  $effect(() => {
    void ctrl.load();
  });
  $effect(() => ctrl.startPolling());

  let confirmingUninstall = $state(false);
  async function confirmUninstall() {
    const ok = await ctrl.uninstall();
    confirmingUninstall = false;
    if (ok) onBack(); // channel no longer exists — return to the list
  }
</script>

<div class="flex flex-col gap-4">
  <div class="flex items-center gap-2">
    <Button variant="ghost" size="sm" onclick={onBack}>
      <ArrowLeft size={15} /> Channels
    </Button>
    <span class="text-sm text-muted-foreground">/</span>
    <span class="font-semibold">{name}</span>
  </div>

  {#if ctrl.loading}
    <Loading label="Loading {name}…" />
  {:else if ctrl.error}
    <Notice message={ctrl.error} />
  {:else}
    <ChannelConnectionCard {ctrl} onRequestUninstall={() => (confirmingUninstall = true)} />

    <Panel title="Settings" contentClass="grid gap-3">
      {#if ctrl.fields.length === 0}
        <EmptyState message="This channel has no configurable settings." />
      {:else}
        <SchemaConfigForm
          fields={ctrl.fields}
          draft={ctrl.draft}
          secretSet={ctrl.secretSet}
          onClearSecret={(key) => ctrl.clearSecret(key)}
        />
        <div class="mt-1 flex items-center gap-3">
          <Button onclick={() => ctrl.save()} disabled={ctrl.saving}>
            {ctrl.saving ? 'Saving…' : 'Save settings'}
          </Button>
          <span class="text-xs text-muted-foreground">
            Applied live to a running channel; otherwise on next Enable.
          </span>
        </div>
      {/if}
    </Panel>
  {/if}
</div>

<ConfirmDialog
  open={confirmingUninstall}
  onOpenChange={(next) => (confirmingUninstall = next)}
  title="Uninstall '{name}'?"
  message="This stops the channel, deletes its configuration, and uninstalls its plugin package. You can install it again later."
  confirmLabel="Uninstall"
  pending={ctrl.uninstalling}
  onConfirm={() => void confirmUninstall()}
/>
