<script lang="ts">
  import { Upload } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import Modal from '$lib/ui/Modal.svelte';

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

  /** Keep a local canvas ref and sync outward so crop preview math uses the modal canvas reliably. */
  let localCropCanvas = $state<HTMLCanvasElement | null>(null);

  /** Avoid re-firing ``onCropCanvasChange`` on unrelated effect runs (prevents redundant ``renderCropPreview`` from parent). */
  let lastSyncedCanvasRef: HTMLCanvasElement | null = null;

  $effect(() => {
    const canvas = localCropCanvas;
    if (canvas === lastSyncedCanvasRef) return;
    lastSyncedCanvasRef = canvas;
    untrack(() => {
      onCropCanvasChange(canvas);
    });
  });

  /** Range inputs use string values; coerce to keep controller sliders numeric. */
  function readSlider(e: Event, apply: (n: number) => void) {
    const raw = Number((e.currentTarget as HTMLInputElement).value);
    if (Number.isNaN(raw)) return;
    apply(raw);
  }
</script>

<Modal
  {open}
  title="Adjust square crop"
  onClose={() => {
    if (!busy) onDismiss();
  }}
>
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
  {#snippet footer()}
    <Button variant="outline" disabled={busy} onclick={onDismiss}>Cancel</Button>
    <Button disabled={busy} onclick={onSubmitPhoto}><Upload size={15} /> Upload</Button>
  {/snippet}
</Modal>
