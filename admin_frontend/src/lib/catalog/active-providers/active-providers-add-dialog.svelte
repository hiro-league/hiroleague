<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import type { AddableProviderRow } from '$lib/api/catalog';

  type Props = {
    open: boolean;
    loading: boolean;
    busy: boolean;
    addableProviders: AddableProviderRow[];
    providerId: string;
    apiKey: string;
    onClose: () => void;
    onSubmit: () => void;
    onProviderIdChange: (value: string) => void;
    onApiKeyChange: (value: string) => void;
  };

  let {
    open,
    loading,
    busy,
    addableProviders,
    providerId,
    apiKey,
    onClose,
    onSubmit,
    onProviderIdChange,
    onApiKeyChange
  }: Props = $props();
</script>

<Dialog.Root {open} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Add provider API key</Dialog.Title>
    </Dialog.Header>
    {#if loading}
      <InlineLoading label="Loading providers…" />
    {:else}
      <div class="grid gap-4">
        <FormField label="Provider">
          {#snippet children()}
            <select
              value={providerId}
              onchange={(event) => onProviderIdChange((event.currentTarget as HTMLSelectElement).value)}
            >
              {#each addableProviders as provider}
                <option value={provider.id}>{provider.display_name} ({provider.id})</option>
              {/each}
            </select>
          {/snippet}
        </FormField>
        <FormField label="API key">
          {#snippet children()}
            <input
              type="password"
              value={apiKey}
              oninput={(event) => onApiKeyChange((event.currentTarget as HTMLInputElement).value)}
              placeholder="Paste the provider API key"
            />
          {/snippet}
        </FormField>
      </div>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={onClose}>Cancel</Button>
      <Button disabled={busy || !providerId || !apiKey.trim()} onclick={onSubmit}>Save</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
