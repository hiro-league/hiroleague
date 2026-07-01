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

// Thinking-level <select> options. The `default` sentinel = model default (persisted as null;
// `updateProfile` / the editor dialog map it back to null). Single source shared by the tuning-profile
// editor dialog and the Model Profiles table row, so the two pickers can't drift.
export const THINKING_SELECT_OPTIONS: { value: string; label: string }[] = [
  { value: 'default', label: 'Model default' },
  { value: 'off', label: 'Off' },
  { value: 'minimal', label: 'Minimal' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' }
];

const THINKING_LABELS: Record<string, string> = {
  off: 'Off',
  minimal: 'Minimal',
  low: 'Low',
  medium: 'Medium',
  high: 'High'
};

/** Short label for a profile's thinking level (the profile summary line); null/undefined → "Default". */
export function thinkingLabel(thinking: ThinkingValue | null | undefined): string {
  return thinking ? (THINKING_LABELS[thinking] ?? thinking) : 'Default';
}
