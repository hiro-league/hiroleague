<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { ToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import type { ImageLabController } from './state/image-lab-controller.svelte';

  let { ctl, toasts }: { ctl: ImageLabController; toasts: ToastNotifier } = $props();
</script>

<Dialog.Root open={ctl.saveDialogOpen} onOpenChange={(next) => { if (!next) ctl.closeSaveDialog(); }}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Save as recipe</Dialog.Title>
      <Dialog.Description>
        Stores the current form (model, steps, seed, style scaffolding) as a named image
        profile in workspace preferences — reusable from the recipe picker, tools, and agents.
      </Dialog.Description>
    </Dialog.Header>
    <div class="grid gap-4">
      <FormField label="Recipe id" hint="Slug: lowercase letters, digits, underscores — e.g. character_portrait.">
        {#snippet children()}
          <input type="text" bind:value={ctl.saveProfileId} placeholder="character_portrait" />
        {/snippet}
      </FormField>
      <FormField label="Label">
        {#snippet children()}
          <input type="text" bind:value={ctl.saveProfileLabel} placeholder="Character portrait" />
        {/snippet}
      </FormField>
      <p class="font-sans text-xs text-muted-foreground">
        Saves: {ctl.model || 'default model'} · steps {ctl.steps} · seed {ctl.seedText.trim() || 'random'}
        {#if ctl.stylePrefix.trim() || ctl.styleSuffix.trim()}
          · with style scaffolding
        {/if}
      </p>
    </div>
    <Dialog.Footer>
      <Button variant="outline" disabled={ctl.saving} onclick={() => ctl.closeSaveDialog()}>Cancel</Button>
      <Button
        disabled={ctl.saving || !ctl.saveProfileId.trim()}
        onclick={() => void ctl.saveProfile(toasts.notify)}
      >
        {ctl.saving ? 'Saving…' : 'Save recipe'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
