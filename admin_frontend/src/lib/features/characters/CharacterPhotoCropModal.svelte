<script lang="ts">
  import { Upload } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import { untrack } from 'svelte';

  let {
    open,
    busy,
    cropZoom,
    cropX,
    cropY,
    onDismiss,
    onCropZoomChange,
    onCropXChange,
    onCropYChange,
    onCropCanvasChange,
    onSubmitPhoto
  }: {
    open: boolean;
    busy: boolean;
    cropZoom: number;
    cropX: number;
    cropY: number;
    onDismiss: () => void;
    onCropZoomChange: (next: number) => void;
    onCropXChange: (next: number) => void;
    onCropYChange: (next: number) => void;
    onCropCanvasChange: (canvas: HTMLCanvasElement | null) => void;
    onSubmitPhoto: () => void;
  } = $props();

  let localCropCanvas = $state<HTMLCanvasElement | null>(null);
  let lastSyncedCanvasRef: HTMLCanvasElement | null = null;

  $effect(() => {
    const canvas = localCropCanvas;
    if (canvas === lastSyncedCanvasRef) return;
    lastSyncedCanvasRef = canvas;
    untrack(() => {
      onCropCanvasChange(canvas);
    });
  });

  function readSlider(e: Event, apply: (n: number) => void) {
    const raw = Number((e.currentTarget as HTMLInputElement).value);
    if (Number.isNaN(raw)) return;
    apply(raw);
  }

  function handleOpenChange(next: boolean) {
    if (next || busy) return;
    onDismiss();
  }
</script>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Adjust square crop</Dialog.Title>
    </Dialog.Header>
    <div class="grid gap-4">
      <canvas
        class="mx-auto aspect-square w-full max-w-96 rounded-md border bg-muted"
        width="512"
        height="512"
        bind:this={localCropCanvas}
      ></canvas>
      <FormField label="Zoom">
        {#snippet children()}
          <input
            min="1"
            max="3"
            step="0.05"
            type="range"
            value={cropZoom}
            oninput={(e) => readSlider(e, onCropZoomChange)}
          />
        {/snippet}
      </FormField>
      <div class="grid gap-3 md:grid-cols-2">
        <FormField label="Horizontal">
          {#snippet children()}
            <input
              min="-100"
              max="100"
              step="1"
              type="range"
              value={cropX}
              oninput={(e) => readSlider(e, onCropXChange)}
            />
          {/snippet}
        </FormField>
        <FormField label="Vertical">
          {#snippet children()}
            <input
              min="-100"
              max="100"
              step="1"
              type="range"
              value={cropY}
              oninput={(e) => readSlider(e, onCropYChange)}
            />
          {/snippet}
        </FormField>
      </div>
    </div>
    <Dialog.Footer>
      <Button variant="outline" disabled={busy} onclick={onDismiss}>Cancel</Button>
      <Button disabled={busy} onclick={onSubmitPhoto}><Upload size={15} /> Upload</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
