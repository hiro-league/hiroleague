<script lang="ts">
  import { Upload } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { Slider } from '$kit/components/ui/slider/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
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
          <Slider type="single" min={1} max={3} step={0.05} value={cropZoom} onValueChange={onCropZoomChange} aria-label="Zoom" />
        {/snippet}
      </FormField>
      <div class="grid gap-3 md:grid-cols-2">
        <FormField label="Horizontal">
          {#snippet children()}
            <Slider type="single" min={-100} max={100} step={1} value={cropX} onValueChange={onCropXChange} aria-label="Horizontal" />
          {/snippet}
        </FormField>
        <FormField label="Vertical">
          {#snippet children()}
            <Slider type="single" min={-100} max={100} step={1} value={cropY} onValueChange={onCropYChange} aria-label="Vertical" />
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
