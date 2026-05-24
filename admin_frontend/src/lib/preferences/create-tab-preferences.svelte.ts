/**
 * Generic page-level tab preferences (URL `?tab=` + session storage).
 *
 * Replaces the four near-identical `*-preferences.svelte.ts` files in this
 * folder (catalog, server, channels-devices, characters) — they collapse to a
 * one-line `createTabPreferences(...)` call once Phase 2 adoption lands.
 *
 * Inner navigation patterns (Preferences `#hash` scroll-spy, Graph runs'
 * underline subtab strip with dynamic per-record tabs) are intentionally
 * *not* covered by this factory — see `docs/admin-frontend-refactor-plan.md`
 * §2.3.
 */
import { goto } from '$app/navigation';
import { page } from '$app/state';
import { readSessionString, writeSessionString } from './storage';

export type TabPreferencesOptions<TTab extends string> = {
  /** `PREF_KEYS.<page>ActiveTab`. Persists the last active tab in `sessionStorage`. */
  storageKey: string;
  /** Tab id used when no URL / session value resolves. */
  defaultTab: TTab;
  /** Whitelist used to validate URL/session values; anything else is ignored. */
  allowed: readonly TTab[];
  /**
   * Extra `?param`s owned by this page that should be cleared whenever the
   * tab changes (unless a caller passes a replacement in `extras`). Typical
   * use: tab-scoped filters such as `provider_id`, `model_kind`.
   */
  urlParamsToReset?: readonly string[];
  /**
   * If `true` (default) the canonical URL omits `?tab=` when the active tab
   * equals `defaultTab` (matches the Knowledge-page behaviour). Set to
   * `false` to always serialise the tab id (Characters/Catalog behaviour).
   */
  omitDefaultFromUrl?: boolean;
};

export type TabPreferences<TTab extends string> = {
  readonly activeTab: TTab;
  /** Read URL → session → default on page mount. */
  initialize: () => void;
  /**
   * Switch active tab; persists session and replaces history entry.
   *
   * @param tab The next tab id.
   * @param extras Additional `?param=value` pairs to set on the URL after
   *   reset (`urlParamsToReset` is honoured first). Empty values are dropped.
   */
  setActiveTab: (tab: TTab, extras?: Record<string, string>) => Promise<void>;
};

export function createTabPreferences<TTab extends string>(
  opts: TabPreferencesOptions<TTab>
): TabPreferences<TTab> {
  const allowedSet = new Set<string>(opts.allowed as readonly string[]);
  const omitDefault = opts.omitDefaultFromUrl ?? false;

  function normalise(raw: string | null): TTab | null {
    return raw !== null && allowedSet.has(raw) ? (raw as TTab) : null;
  }

  let activeTab = $state<TTab>(opts.defaultTab);

  function initialize() {
    activeTab =
      normalise(page.url.searchParams.get('tab')) ??
      normalise(readSessionString(opts.storageKey)) ??
      opts.defaultTab;
  }

  async function setActiveTab(tab: TTab, extras: Record<string, string> = {}) {
    activeTab = tab;
    writeSessionString(opts.storageKey, tab);

    const nextUrl = new URL(page.url);
    if (omitDefault && tab === opts.defaultTab) {
      nextUrl.searchParams.delete('tab');
    } else {
      nextUrl.searchParams.set('tab', tab);
    }

    if (opts.urlParamsToReset) {
      for (const key of opts.urlParamsToReset) {
        nextUrl.searchParams.delete(key);
      }
    }

    for (const [key, value] of Object.entries(extras)) {
      if (value.trim()) {
        nextUrl.searchParams.set(key, value);
      } else {
        nextUrl.searchParams.delete(key);
      }
    }

    const next = `${nextUrl.pathname}${nextUrl.search}`;
    const current = `${page.url.pathname}${page.url.search}`;
    if (next === current) return;

    await goto(next, {
      keepFocus: true,
      noScroll: true,
      replaceState: true
    });
  }

  return {
    get activeTab() {
      return activeTab;
    },
    initialize,
    setActiveTab
  };
}
