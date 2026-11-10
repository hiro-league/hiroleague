export type ModalityKey = 'voice' | 'image' | 'video' | 'file';

export const modalityKeys: ModalityKey[] = ['voice', 'image', 'video', 'file'];

export const modalityLabels: Record<ModalityKey, string> = {
  voice: 'Voice',
  image: 'Image',
  video: 'Video',
  file: 'File'
};

export const rerankerDeviceOptions: { value: string; label: string }[] = [
  { value: 'auto', label: 'Auto (CUDA if available)' },
  { value: 'cpu', label: 'CPU' },
  { value: 'cuda', label: 'CUDA' }
];
