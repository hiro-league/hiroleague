import { createPoller } from '$lib/state/create-poller.svelte';
import type { LogsPageController } from '../state/logs-controller.svelte';
import type { LogsPreferences } from '$lib/preferences/logs-preferences.svelte';

export const LOGS_POLL_INTERVAL_MS = 500;

/** URL ``msg_id`` wins over session-restored ``scopeMsgId`` when non-empty. */
export function scopeMsgIdAfterHydrate(
  sessionScopeMsgId: string,
  urlMsgId: string | null | undefined
): string {
  const fromUrl = (urlMsgId ?? '').trim();
  return fromUrl || sessionScopeMsgId;
}

/**
 * Session hydrate, initial load, polling interval, and teardown. The logs page now
 * scrolls with the document (sticky header + sticky filter toolbar like other pages),
 * so the former document-scroll lock was removed.
 */
export function setupLogsPageRuntime(opts: {
  prefs: LogsPreferences;
  ctrl: LogsPageController;
  /** When set (e.g. from ``/logs?msg_id=``), overrides session-restored ``scopeMsgId`` before the first fetch. */
  urlMsgId?: string | null;
}) {
  const { prefs, ctrl, urlMsgId } = opts;

  prefs.scopeMsgId = scopeMsgIdAfterHydrate(prefs.scopeMsgId, urlMsgId);
  void ctrl.initialize();
  const logsPoller = createPoller(() => ctrl.poll(), {
    intervalMs: LOGS_POLL_INTERVAL_MS,
    pauseWhenHidden: true
  });
  const stopPoll = logsPoller.start();

  // Close log details on Escape from anywhere on the page while the panel is open (stable
  // handler reference required for removeEventListener in teardown).
  function onDocumentKeydown(event: KeyboardEvent) {
    if (event.key !== 'Escape' || !prefs.detailPanelOpen) return;
    event.preventDefault();
    prefs.detailPanelOpen = false;
  }
  window.addEventListener('keydown', onDocumentKeydown);

  return () => {
    window.removeEventListener('keydown', onDocumentKeydown);
    stopPoll();
    ctrl.dispose();
  };
}
