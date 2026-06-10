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
    accountId: string;
    onClose: () => void;
    onSubmit: () => void;
    onProviderIdChange: (value: string) => void;
    onApiKeyChange: (value: string) => void;
    onAccountIdChange: (value: string) => void;
  };

  let {
    open,
    loading,
    busy,
    addableProviders,
    providerId,
    apiKey,
    accountId,
    onClose,
    onSubmit,
    onProviderIdChange,
    onApiKeyChange,
    onAccountIdChange
  }: Props = $props();

  // Cloudflare-style vendors embed a non-secret account id in their REST URL.
  const requiresAccountId = $derived(
    addableProviders.find((provider) => provider.id === providerId)?.requires_account_id ?? false
  );
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
        {#if requiresAccountId}
          <FormField
            label="Account ID"
            hint="Non-secret vendor account identifier (part of the API URL) — e.g. the Cloudflare account id from the dashboard."
          >
            {#snippet children()}
              <input
                type="text"
                value={accountId}
                oninput={(event) => onAccountIdChange((event.currentTarget as HTMLInputElement).value)}
                placeholder="Paste the provider account id"
              />
            {/snippet}
          </FormField>
        {/if}
      </div>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={onClose}>Cancel</Button>
      <Button
        disabled={busy || !providerId || !apiKey.trim() || (requiresAccountId && !accountId.trim())}
        onclick={onSubmit}
      >
        Save
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
