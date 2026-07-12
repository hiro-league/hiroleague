<script lang="ts">
  import { untrack } from 'svelte';
  import { ArrowLeft } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import { ADMIN_SECTION_TITLE } from '$lib/styling/admin-tokens';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import type { Notify } from '$lib/ui/toast-types';
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
    <InlineLoading label="Loading {name}…" />
  {:else if ctrl.error}
    <InlineDestructiveAlert message={ctrl.error} />
  {:else}
    <ChannelConnectionCard {ctrl} />

    <SectionCard class="grid gap-3">
      <h2 class={ADMIN_SECTION_TITLE}>Settings</h2>
      {#if ctrl.fields.length === 0}
        <InlineEmptyState message="This channel has no configurable settings." />
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
          <span class="text-xs text-muted-foreground">Changes apply after a server restart.</span>
        </div>
      {/if}
    </SectionCard>
  {/if}
</div>
