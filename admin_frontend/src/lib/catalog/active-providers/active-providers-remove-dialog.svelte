<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { ActiveProviderRow } from '$lib/api/catalog';

  type Props = {
    open: boolean;
    busy: boolean;
    provider: ActiveProviderRow | null;
    onClose: () => void;
    onSubmit: () => void;
  };

  let { open, busy, provider, onClose, onSubmit }: Props = $props();
</script>

<Dialog.Root {open} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Remove provider '{provider?.provider_id ?? ''}'</Dialog.Title>
      {#if provider?.display_name}
        <Dialog.Description>{provider.display_name}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">
      This removes stored credentials for the selected workspace. Models from this provider will be
      unavailable until credentials are added again.
    </p>
    <Dialog.Footer>
      <Button variant="outline" onclick={onClose}>Cancel</Button>
      <Button variant="destructive" disabled={busy} onclick={onSubmit}>Remove</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
