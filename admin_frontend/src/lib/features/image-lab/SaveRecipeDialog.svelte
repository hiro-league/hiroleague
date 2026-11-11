<script lang="ts">
  import { Button } from '$kit/components/ui/button/index.js';
  import Field from '$kit/ui/field.svelte';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import { Input } from '$kit/components/ui/input/index.js';
  import { toast } from '$kit/ui/toast.svelte';
  import type { ImageLabController } from './state/image-lab-controller.svelte';

  let { ctl }: { ctl: ImageLabController } = $props();
  const uid = $props.id();
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
      <Field label="Recipe id" for="{uid}-id" hint="Slug: lowercase letters, digits, underscores — e.g. character_portrait.">
        <Input id="{uid}-id" type="text" bind:value={ctl.saveProfileId} placeholder="character_portrait" />
      </Field>
      <Field label="Label" for="{uid}-label">
        <Input id="{uid}-label" type="text" bind:value={ctl.saveProfileLabel} placeholder="Character portrait" />
      </Field>
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
        onclick={() => void ctl.saveProfile(toast.show)}
      >
        {ctl.saving ? 'Saving…' : 'Save recipe'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
