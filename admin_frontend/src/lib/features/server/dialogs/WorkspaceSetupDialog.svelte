<script lang="ts">
  import { CircleHelp } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let { workspace }: { workspace: ReturnType<typeof createWorkspaceStore> } = $props();
</script>

<Dialog.Root
  open={workspace.dialog === 'setup'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Setup workspace '{workspace.selected?.name ?? ''}'</Dialog.Title>
      {#if workspace.selected?.path}
        <Dialog.Description>{workspace.selected.path}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <div class="grid gap-4">
      <FormField label="Gateway WebSocket URL">
        {#snippet children()}
          <input bind:value={workspace.setupForm.gatewayUrl} placeholder="ws://myhost:8765" />
        {/snippet}
      </FormField>
      <details class="grid gap-3 rounded-md border bg-muted/40 p-3">
        <summary class="cursor-pointer font-sans font-semibold">Advanced options</summary>
        <FormField label="HTTP port override">
          {#snippet children()}
            <input
              bind:value={workspace.setupForm.httpPort}
              inputmode="numeric"
              placeholder={`Auto-assigned: ${workspace.selected?.http_port ?? ''}`}
            />
          {/snippet}
        </FormField>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={workspace.setupForm.skipAutostart} />
          Skip auto-start registration
          <CircleHelp size={14} title="By default, the server is registered to start automatically on login." />
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={workspace.setupForm.startServer} />
          Start server immediately after setup
          <CircleHelp size={14} title="Start this workspace as soon as setup saves the gateway URL and keys." />
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={workspace.setupForm.elevatedTask} />
          Request elevated Task Scheduler entry
          <CircleHelp
            size={14}
            title="Windows only. Triggers a UAC prompt on the server machine and registers the startup task with highest privileges."
          />
        </label>
      </details>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitSetup}>Run setup</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
