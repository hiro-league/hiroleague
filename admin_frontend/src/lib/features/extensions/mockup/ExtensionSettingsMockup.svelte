<script lang="ts">
  // mockup: one extension's Settings, edited in place: its linked account (WhatsApp's QR code) and its settings
  // form, drawn from its config_schema. Opened from the row's Settings button; nothing in it opens another panel.
  import { QrCode } from '@lucide/svelte';
  import { Input } from '$kit/components/ui/input/index.js';
  import { Switch } from '$kit/components/ui/switch/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import EditorSheet from '$kit/ui/editor-sheet.svelte';
  import Field from '$kit/ui/field.svelte';
  import SectionLabel from '$kit/ui/section-label.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import type { OneListMockup } from './one-list-mockup.svelte';

  let { list }: { list: OneListMockup } = $props();
  const uid = $props.id();

  const row = $derived(list.panel === 'settings' ? list.selected : null);
  const form = $derived(list.settingsForm);
  // The sheet is open while a row is picked for Settings; closing it (after the sheet's own "discard?") un-picks it.
  const getOpen = () => row !== null;
  const setOpen = (next: boolean) => {
    if (!next) list.close();
  };
  // The QR code shows in this panel, under the account line, while the person links the account.
  let showQr = $state(false);
  $effect(() => {
    if (!row) showQr = false;
  });
</script>

<EditorSheet
  bind:open={getOpen, setOpen}
  title={row ? `${row.label} settings` : ''}
  saveLabel="Save"
  canSave={form.dirty && !form.action.busy}
  dirty={form.dirty}
  error={form.action.error}
  onsave={() => void form.save()}
>
  {#if row}
    {#if row.link}
      <section class="grid gap-2">
        <SectionLabel>
          Its account
          {#snippet actions()}
            <Button size="sm" variant="outline" onclick={() => (showQr = !showQr)}>
              <QrCode size={13} /> {showQr ? 'Hide the QR code' : row.link?.linked ? 'Link again' : 'Link'}
            </Button>
          {/snippet}
        </SectionLabel>
        <span class="flex items-center gap-2">
          <StatusDot tone={row.link.linked ? 'ok' : 'warn'} />
          {row.link.linked ? `Linked: ${row.link.account}` : 'Not linked'}
        </span>
        {#if showQr}
          <div class="grid justify-items-center gap-2 rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
            <div class="grid size-40 place-items-center rounded-md bg-muted"><QrCode size={56} /></div>
            Scan it from the phone: WhatsApp, Linked devices, Link a device.
          </div>
        {/if}
      </section>
    {/if}

    <section class="grid gap-3">
      <SectionLabel>Settings</SectionLabel>
      {#if form.value?.length}
        {#each form.value as s (s.key)}
          {#if s.kind === 'bool'}
            <label class="flex items-center justify-between gap-3">
              <span>{s.label}</span>
              <Switch bind:checked={s.value} aria-label={s.label} />
            </label>
          {:else if s.kind === 'secret'}
            <Field label={s.label} for="{uid}-{s.key}" hint={s.set ? 'Set. Type to replace it.' : 'Not set.'}>
              <Input id="{uid}-{s.key}" type="password" bind:value={s.value} placeholder={s.set ? '•••••••• set' : 'not set'} />
            </Field>
          {:else}
            <Field label={s.label} for="{uid}-{s.key}">
              <Input id="{uid}-{s.key}" bind:value={s.value} />
            </Field>
          {/if}
        {/each}
      {:else}
        <p class="text-muted-foreground">It has no settings.</p>
      {/if}
    </section>
  {/if}
</EditorSheet>
