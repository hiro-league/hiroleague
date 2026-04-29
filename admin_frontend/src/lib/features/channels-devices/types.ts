export type NotifyKind = 'success' | 'error' | 'info' | 'warning';

export type Notify = (kind: NotifyKind, message: string) => void;
