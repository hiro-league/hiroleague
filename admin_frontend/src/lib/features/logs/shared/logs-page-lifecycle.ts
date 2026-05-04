import type { LogsPageController } from '../state/logs-controller.svelte';
import type { LogsPreferences } from '../state/logs-preferences.svelte';

/**
 * Applied to ``document.documentElement`` while the logs page is mounted so the app shell
 * does not scroll behind the full-height log workspace. Keep in sync with the ``:global``
 * rule in ``LogsPage.svelte``.
 */
export const LOGS_NO_DOCUMENT_SCROLL_CLASS = 'admin-logs-no-document-scroll';

export const LOGS_POLL_INTERVAL_MS = 500;

/** Document scroll lock, session hydrate, initial load, polling interval, and teardown. */
export function setupLogsPageRuntime(opts: { prefs: LogsPreferences; ctrl: LogsPageController }) {
  const { prefs, ctrl } = opts;

  document.documentElement.classList.add(LOGS_NO_DOCUMENT_SCROLL_CLASS);
  prefs.hydrateFromSession();
  void ctrl.initialize();
  const interval = window.setInterval(() => void ctrl.poll(), LOGS_POLL_INTERVAL_MS);

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
    document.documentElement.classList.remove(LOGS_NO_DOCUMENT_SCROLL_CLASS);
    window.clearInterval(interval);
    ctrl.dispose();
  };
}
