/**
 * Canonical toast notifier factory.
 *
 * Replaces the per-page `notify()` + `toast` `$state` + `setTimeout` recipe
 * that lived inside ~10 features. Each page does:
 *
 * ```ts
 * const toasts = createToastNotifier();
 * // ...
 * toasts.notify('success', 'Saved');
 * ```
 *
 * and renders `<ToastHost toast={toasts.toast} />`. See
 * `docs/admin-frontend-refactor-plan.md` §3.1 and §4 (Phase 2).
 */
import type { ToastKind, ToastMessage } from './toast-types';
import { serverReadiness } from '$lib/runtime/server-readiness.svelte';

const DEFAULT_TIMEOUT_MS = 4500;

export type ToastNotifier = {
  readonly toast: ToastMessage;
  notify: (kind: ToastKind, message: string) => void;
  clear: () => void;
};

export function createToastNotifier(timeoutMs: number = DEFAULT_TIMEOUT_MS): ToastNotifier {
  let toast = $state<ToastMessage>(null);
  let handle = 0;

  function clear() {
    if (handle) {
      window.clearTimeout(handle);
      handle = 0;
    }
    toast = null;
  }

  function notify(kind: ToastKind, message: string) {
    // Shell banner owns server-outage messaging — skip redundant error toasts.
    if (kind === 'error' && !serverReadiness.ready) return;
    if (handle) {
      window.clearTimeout(handle);
    }
    toast = { kind, message };
    handle = window.setTimeout(() => {
      toast = null;
      handle = 0;
    }, timeoutMs);
  }

  return {
    get toast() {
      return toast;
    },
    notify,
    clear
  };
}
