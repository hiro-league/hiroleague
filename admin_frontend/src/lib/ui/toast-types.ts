/** Toast notification primitives shared by `ToastHost.svelte` and `createToastNotifier`. */

export type ToastKind = 'success' | 'error' | 'info' | 'warning';

export type ToastMessage = { kind: ToastKind; message: string } | null;

/** Callback shape a feature receives to surface a toast (e.g. from a store/controller). */
export type Notify = (kind: ToastKind, message: string) => void;
