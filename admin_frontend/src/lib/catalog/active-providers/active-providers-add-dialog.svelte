<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import type { AddableProviderRow } from '$lib/api/catalog';

  import type { ProviderCheckResult } from '$lib/api/catalog';

  type Props = {
    open: boolean;
    loading: boolean;
    busy: boolean;
    addableProviders: AddableProviderRow[];
    providerId: string;
    apiKey: string;
    accountId: string;
    baseUrl: string;
    checking: boolean;
    checkResult: ProviderCheckResult | null;
    onClose: () => void;
    onSubmit: () => void;
    onTest: () => void;
    onProviderIdChange: (value: string) => void;
    onApiKeyChange: (value: string) => void;
    onAccountIdChange: (value: string) => void;
    onBaseUrlChange: (value: string) => void;
  };

  let {
    open,
    loading,
    busy,
    addableProviders,
    providerId,
    apiKey,
    accountId,
    baseUrl,
    checking,
    checkResult,
    onClose,
    onSubmit,
    onTest,
    onProviderIdChange,
    onApiKeyChange,
    onAccountIdChange,
    onBaseUrlChange
  }: Props = $props();

  // Cataloged models not yet pulled on the probed server — surfaced with their `ollama pull` hint.
  const missingModels = $derived(
    (checkResult?.catalog_status ?? []).filter((m) => !m.pulled)
  );

  const selectedProvider = $derived(addableProviders.find((provider) => provider.id === providerId));
  // Local providers (Ollama, LM Studio) are configured by HTTP endpoint, not an API key.
  const isLocal = $derived(selectedProvider?.auth_method === 'local_endpoint');
  // Cloudflare-style vendors embed a non-secret account id in their REST URL.
  const requiresAccountId = $derived(selectedProvider?.requires_account_id ?? false);
  // Save gating differs by mode: local needs a base URL; cloud needs a key (+ account id if required).
  const canSave = $derived(
    !!providerId &&
      (isLocal
        ? !!baseUrl.trim()
        : !!apiKey.trim() && (!requiresAccountId || !!accountId.trim()))
  );
</script>

<Dialog.Root {open} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Add provider</Dialog.Title>
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
        {#if isLocal}
          <FormField
            label="Endpoint URL"
            hint="HTTP base URL of the local server — no API key. Ollama defaults to http://localhost:11434."
          >
            {#snippet children()}
              <input
                type="text"
                value={baseUrl}
                oninput={(event) => onBaseUrlChange((event.currentTarget as HTMLInputElement).value)}
                placeholder="http://localhost:11434"
              />
            {/snippet}
          </FormField>
          <div class="grid gap-2">
            <Button
              variant="outline"
              class="justify-self-start"
              disabled={busy || checking || !baseUrl.trim()}
              onclick={onTest}
            >
              {checking ? 'Testing…' : 'Test connection'}
            </Button>
            {#if checkResult}
              {#if checkResult.online}
                <p class="text-sm text-green-700 dark:text-green-500">
                  ✅ Online — {checkResult.installed.length} model{checkResult.installed.length === 1
                    ? ''
                    : 's'} installed{checkResult.latency_ms != null
                    ? ` · ${checkResult.latency_ms} ms`
                    : ''}
                </p>
                {#if missingModels.length > 0}
                  <div class="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs dark:border-amber-800 dark:bg-amber-950/40">
                    <p class="mb-1 font-medium text-amber-800 dark:text-amber-300">
                      Cataloged models not pulled yet:
                    </p>
                    <ul class="grid gap-1">
                      {#each missingModels as model}
                        <li>
                          <span class="text-muted-foreground">{model.name}</span>
                          {#if model.pull_cmd}
                            — <code class="rounded bg-muted px-1 py-0.5">{model.pull_cmd}</code>
                          {/if}
                        </li>
                      {/each}
                    </ul>
                  </div>
                {/if}
              {:else}
                <p class="text-sm text-destructive">
                  ❌ Offline{checkResult.error ? ` — ${checkResult.error}` : ''}
                </p>
              {/if}
            {/if}
          </div>
        {:else}
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
        {/if}
      </div>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={onClose}>Cancel</Button>
      <Button disabled={busy || !canSave} onclick={onSubmit}>Save</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
