/** Toast notification primitives shared by `ToastHost.svelte` and `createToastNotifier`. */

export type ToastKind = 'success' | 'error' | 'info' | 'warning';

export type ToastMessage = { kind: ToastKind; message: string } | null;
