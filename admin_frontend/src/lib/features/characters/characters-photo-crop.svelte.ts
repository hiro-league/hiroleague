import { tick } from 'svelte';
import { uploadCharacterPhoto } from '$lib/api/characters';

type NotifyKind = 'success' | 'error' | 'info' | 'warning';

/** Avatar square-crop modal + canvas pipeline (Characters edit). Wired into page controller via callbacks. */
export function createCharactersPhotoCrop(opts: {
  getCharacterId: () => string;
  notify: (kind: NotifyKind, message: string) => void;
  setBusy: (busy: boolean) => void;
  onAfterPhotoUpload: () => Promise<void>;
}) {
  const { getCharacterId, notify, setBusy, onAfterPhotoUpload } = opts;

  let avatarCropModalOpen = $state(false);
  let cropZoom = $state(1);
  let cropX = $state(0);
  let cropY = $state(0);
  /** Canvas bound from crop modal — source for exported PNG crop. */
  let cropCanvas = $state<HTMLCanvasElement | null>(null);

  /** Decoded bitmap for cropping; released when modal closes implicitly. */
  let cropImage: HTMLImageElement | null = null;

  function readFileAsDataUrl(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result ?? ''));
      reader.onerror = () => reject(new Error('Failed to read image file.'));
      reader.readAsDataURL(file);
    });
  }

  async function pickPhoto(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const characterId = getCharacterId().trim();
    if (!characterId) {
      notify('warning', 'Save the character before uploading a photo.');
      return;
    }
    try {
      const dataUrl = await readFileAsDataUrl(file);
      const img = new Image();
      img.onload = async () => {
        cropImage = img;
        cropZoom = 1;
        cropX = 0;
        cropY = 0;
        avatarCropModalOpen = true;
        await tick();
        renderCropPreview();
      };
      img.onerror = () => {
        notify('error', 'Could not decode that image. Try PNG or JPEG.');
      };
      img.src = dataUrl;
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to read image file.');
    }
  }

  function renderCropPreview() {
    const canvas = cropCanvas;
    const image = cropImage;
    if (!canvas || !image) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    const baseSide = Math.min(image.naturalWidth, image.naturalHeight);
    const side = baseSide / cropZoom;
    const maxX = Math.max(0, image.naturalWidth - side);
    const maxY = Math.max(0, image.naturalHeight - side);
    const sx = Math.min(maxX, Math.max(0, maxX / 2 + (cropX / 100) * (maxX / 2)));
    const sy = Math.min(maxY, Math.max(0, maxY / 2 + (cropY / 100) * (maxY / 2)));

    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, sx, sy, side, side, 0, 0, canvas.width, canvas.height);
  }

  async function submitPhoto() {
    const canvas = cropCanvas;
    const characterId = getCharacterId().trim();
    if (!canvas || !characterId) return;
    setBusy(true);
    try {
      const payload = await uploadCharacterPhoto(characterId, canvas.toDataURL('image/png'));
      notify('success', `Photo updated (${payload.data}).`);
      avatarCropModalOpen = false;
      await onAfterPhotoUpload();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      setBusy(false);
    }
  }

  function dismissCropModal() {
    avatarCropModalOpen = false;
  }

  function handleCropZoom(next: number) {
    cropZoom = next;
    renderCropPreview();
  }

  function handleCropPanX(next: number) {
    cropX = next;
    renderCropPreview();
  }

  function handleCropPanY(next: number) {
    cropY = next;
    renderCropPreview();
  }

  /** Called when modal attaches canvas ``<canvas bind:this>`` — redraw once element exists. */
  function handleCropCanvas(el: HTMLCanvasElement | null) {
    cropCanvas = el;
    renderCropPreview();
  }

  return {
    pickPhoto,
    submitPhoto,
    renderCropPreview,
    dismissCropModal,
    handleCropZoom,
    handleCropPanX,
    handleCropPanY,
    handleCropCanvas,

    get cropOpen(): boolean {
      return avatarCropModalOpen;
    },
    set cropOpen(open: boolean) {
      avatarCropModalOpen = open;
    },

    get cropZoom(): number {
      return cropZoom;
    },
    set cropZoom(v: number) {
      cropZoom = v;
    },

    get cropX(): number {
      return cropX;
    },
    set cropX(v: number) {
      cropX = v;
    },

    get cropY(): number {
      return cropY;
    },
    set cropY(v: number) {
      cropY = v;
    },

    get cropCanvas(): HTMLCanvasElement | null {
      return cropCanvas;
    },
    set cropCanvas(v: HTMLCanvasElement | null) {
      cropCanvas = v;
    }
  };
}
