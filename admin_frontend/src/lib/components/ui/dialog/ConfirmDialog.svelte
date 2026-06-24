<script lang="ts">
  import type { Snippet } from 'svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';

  let {
    open,
    onOpenChange,
    title,
    message,
    description,
    confirmLabel,
    cancelLabel = 'Cancel',
    destructive = true,
    pending = false,
    disableCancelWhenPending = false,
    widthClass = 'sm:max-w-md',
    showCloseButton = true,
    onConfirm,
    children
  }: {
    open: boolean;
    // Required: Cancel and the X close button both route through this, so an omitted
    // handler would yield an undismissable dialog. Make that a compile-time error.
    onOpenChange: (next: boolean) => void;
    title: string;
    message?: string;
    /** Rich Dialog.Description inside the header (when plain `message` is not enough). */
    description?: Snippet;
    confirmLabel: string;
    cancelLabel?: string;
    destructive?: boolean;
    pending?: boolean;
    disableCancelWhenPending?: boolean;
    widthClass?: string;
    showCloseButton?: boolean;
    onConfirm: () => void | Promise<void>;
    children?: Snippet;
  } = $props();

  const cancelDisabled = $derived(disableCancelWhenPending && pending);
</script>

<Dialog.Root {open} {onOpenChange}>
  <Dialog.Content class={widthClass} {showCloseButton}>
    <Dialog.Header>
      <Dialog.Title class="break-words">{title}</Dialog.Title>
      {#if message}
        <Dialog.Description>{message}</Dialog.Description>
      {:else if description}
        {@render description()}
      {/if}
    </Dialog.Header>

    {#if children}
      {@render children()}
    {/if}

    <Dialog.Footer>
      <Button variant="outline" disabled={cancelDisabled} onclick={() => onOpenChange(false)}>
        {cancelLabel}
      </Button>
      <Button
        variant={destructive ? 'destructive' : 'default'}
        disabled={pending}
        onclick={() => void onConfirm()}
      >
        {confirmLabel}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
