<script lang="ts">
  import { ImageIcon, Upload } from '@lucide/svelte';
  import type { CharacterRow } from '$lib/api/characters';
  import FormField from '$lib/components/ui/form-field.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import { dialogCloseAllowed } from '$lib/components/ui/dialog/dialog-close-guard';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import type { ChatChannelFormFields } from '$lib/features/chat-channels/shared/chat-channel-form';

  type Props = {
    open: boolean;
    title: string;
    busy: boolean;
    formMode: 'create' | 'edit';
    form: ChatChannelFormFields;
    pendingPhotoDataUrl: string | null;
    modalChannelPhotoSrc: string | null;
    formError: string | null;
    characters: CharacterRow[];
    characterLabel: (id: string) => string;
    onBeforeClose: (source: 'backdrop' | 'escape' | 'header') => boolean;
    onDismiss: () => void;
    onCancelExplicit: () => void;
    onSubmit: () => void;
  };

  let {
    open,
    title,
    busy,
    formMode,
    form = $bindable(),
    pendingPhotoDataUrl = $bindable(),
    modalChannelPhotoSrc,
    formError,
    characters,
    characterLabel,
    onBeforeClose,
    onDismiss,
    onCancelExplicit,
    onSubmit
  }: Props = $props();

  let channelPhotoInput = $state<HTMLInputElement | null>(null);

  function onPhotoFile(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || !file.type.startsWith('image/')) return;
    const reader = new FileReader();
    reader.onload = () => {
      pendingPhotoDataUrl = typeof reader.result === 'string' ? reader.result : null;
      input.value = '';
    };
    reader.readAsDataURL(file);
  }

  function pickPhoto(): void {
    channelPhotoInput?.click();
  }

  function handleOpenChange(next: boolean) {
    if (next) return;
    if (!dialogCloseAllowed(onBeforeClose, 'escape')) return;
    onDismiss();
  }
</script>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
  <Dialog.Content
    class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-xl"
    onInteractOutside={(event) => {
      if (!dialogCloseAllowed(onBeforeClose, 'backdrop')) event.preventDefault();
    }}
    onEscapeKeydown={(event) => {
      if (!dialogCloseAllowed(onBeforeClose, 'escape')) event.preventDefault();
    }}
  >
    <Dialog.Header>
      <Dialog.Title>{title}</Dialog.Title>
    </Dialog.Header>

    <div class="grid gap-6 lg:grid-cols-[160px_minmax(0,1fr)] lg:items-start [&_.admin-ui-form-field]:mb-0">
      <div class="grid justify-items-start gap-3">
        <input
          class="hidden"
          type="file"
          accept="image/*"
          bind:this={channelPhotoInput}
          onchange={onPhotoFile}
        />
        <button
          type="button"
          class="overflow-hidden rounded-md border bg-muted/30 p-0 text-left ring-offset-background transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onclick={pickPhoto}
        >
          {#if modalChannelPhotoSrc}
            <img class="size-36 object-cover sm:size-40" src={modalChannelPhotoSrc} alt="" />
          {:else}
            <span class="grid size-36 place-items-center text-muted-foreground sm:size-40">
              <ImageIcon size={40} />
            </span>
          {/if}
        </button>
        <Button variant="outline" class="w-full max-w-40" onclick={pickPhoto}>
          <Upload size={15} /> Photo
        </Button>
      </div>

      <div class="grid min-w-0 gap-4">
        <FormField label="Display name" class="mb-4 w-full md:max-w-[33%] md:min-w-[12rem]">
          {#snippet children()}
            <input bind:value={form.name} autocomplete="off" />
          {/snippet}
        </FormField>

        <FormField label="Description" class="mb-4">
          {#snippet children()}
            <textarea class="min-h-24" bind:value={form.description} autocomplete="off"></textarea>
          {/snippet}
        </FormField>

        <FormField label="Character">
          {#snippet children()}
            <select bind:value={form.characterId}>
              {#each characters as c (c.id)}
                <option value={c.id}>{characterLabel(c.id)}</option>
              {/each}
            </select>
          {/snippet}
        </FormField>

        <FormField label="Type">
          {#snippet children()}
            <select class="opacity-70" aria-readonly="true" disabled title="Conversation type">
              <option value="direct" selected>direct</option>
            </select>
          {/snippet}
        </FormField>
      </div>
    </div>

    {#if formError}
      <InlineDestructiveAlert message={formError} />
    {/if}

    <Dialog.Footer>
      <Button variant="outline" onclick={onCancelExplicit}>Cancel</Button>
      <Button disabled={busy} onclick={onSubmit}>{formMode === 'create' ? 'Create' : 'Save'}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
