export type ModalityKey = 'voice' | 'image' | 'video' | 'file';
export type ThinkingValue = 'off' | 'minimal' | 'low' | 'medium' | 'high';

export const modalityKeys: ModalityKey[] = ['voice', 'image', 'video', 'file'];

export const modalityLabels: Record<ModalityKey, string> = {
  voice: 'Voice',
  image: 'Image',
  video: 'Video',
  file: 'File'
};

export const rerankerModelOptions: { id: string; label: string }[] = [
  { id: 'cross-encoder/ms-marco-MiniLM-L-6-v2', label: 'MS MARCO MiniLM L-6 (default)' },
  { id: 'cross-encoder/ms-marco-TinyBERT-L-2-v2', label: 'MS MARCO TinyBERT L-2 (fastest)' },
  { id: 'cross-encoder/ms-marco-electra-base', label: 'MS MARCO ELECTRA base (higher quality)' }
];

export const rerankerDeviceOptions: { value: string; label: string }[] = [
  { value: 'auto', label: 'Auto (CUDA if available)' },
  { value: 'cpu', label: 'CPU' },
  { value: 'cuda', label: 'CUDA' }
];
