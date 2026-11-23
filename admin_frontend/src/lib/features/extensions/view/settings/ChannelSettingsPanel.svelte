<script lang="ts">
  // One channel's Settings, edited in place: its account (live state, the QR code to link it, its declared actions)
  // and its settings form. Made per channel (keyed where it is used); nothing in it opens another panel.
  import { untrack } from 'svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import EditorSheet from '$kit/ui/editor-sheet.svelte';
  import Loading from '$kit/ui/loading.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import SectionLabel from '$kit/ui/section-label.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import { poll } from '$kit/state/poll.svelte';
  import type { Notify } from '$kit/ui/toast.svelte';
  import { createChannelSettings } from '../../state/channel-settings.svelte';
  import SchemaConfigForm from './SchemaConfigForm.svelte';

  interface Props {
    name: string;
    label: string;
    /** Its switch: an account is linked, logged out or reconnected only while the channel runs. */
    enabled: boolean;
    notify: Notify;
    onclose: () => void;
  }
  let { name, label, enabled, notify, onclose }: Props = $props();

  // Keyed by the channel where it is used, so its props are read once on purpose.
  const c = untrack(() => createChannelSettings(name, notify));
  void c.load();
  // The account's state and its QR code, read again while the panel is open.
  poll(() => c.refreshStatus(), 2500);

  const getOpen = () => true;
  const setOpen = (next: boolean) => {
    if (!next) onclose();
  };

  async function save() {
    await c.form.save();
    if (!c.form.action.error) onclose();
  }
</script>

<EditorSheet
  bind:open={getOpen, setOpen}
  title="{label} settings"
  saveLabel="Save"
  canSave={c.form.dirty && !c.form.action.busy}
  dirty={c.form.dirty}
  error={c.form.action.error}
  onsave={() => void save()}
>
  {#if !c.loaded}
    <Loading label="Loading {label}…" />
  {:else}
    {#if c.error}<Notice message={c.error} />{/if}

    {#if c.pairingKind}
      <section class="grid gap-2">
        <SectionLabel>
          Its account
          {#snippet actions()}
            {#each enabled ? c.actions : [] as action (action)}
              <Button size="sm" variant="outline" disabled={c.acting} onclick={() => void c.runAction(action)}>
                {c.actionLabel(action)}
              </Button>
            {/each}
          {/snippet}
        </SectionLabel>
        <span class="flex items-center gap-2">
          <StatusDot tone={!enabled ? 'off' : c.linked ? 'ok' : c.needsRepair ? 'error' : 'warn'} />
          {#if !enabled}
            Off: switch it on to link its account.
          {:else if c.linked}
            Linked{c.status?.account ? `: ${c.status.account}` : ''}
          {:else}
            Not linked <span class="text-muted-foreground">({c.status?.state ?? 'unknown'})</span>
          {/if}
        </span>
        {#if c.needsRepair && c.repairMessage}<Notice message={c.repairMessage} />{/if}
        {#if c.qrImage}
          <div class="grid justify-items-center gap-2 rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
            <img src={c.qrImage} alt="The QR code that links {label}" class="size-52 rounded-md bg-white p-2" />
            Open the app on the phone: Linked devices, Link a device, then scan this code.
          </div>
        {:else if enabled && !c.linked && c.pairingKind === 'qr'}
          <p class="text-xs text-muted-foreground">
            Its QR code shows here once the channel is on and asks to be linked.
          </p>
        {/if}
      </section>
    {/if}

    <section class="grid gap-3">
      <SectionLabel>Settings</SectionLabel>
      {#if c.fields.length}
        <SchemaConfigForm
          fields={c.fields}
          draft={c.form.value}
          secretSet={c.secretSet}
          onClearSecret={(key) => void c.clearSecret(key)}
        />
      {:else}
        <p class="text-muted-foreground">It has no settings.</p>
      {/if}
    </section>
  {/if}
</EditorSheet>
