/**
 * Knowledge page URL tab hydration / persistence (`?tab=ingest|browse|ask`).
 */
import { goto } from '$app/navigation';
import { normalizeKnowledgeTab, type KnowledgeTabId } from './knowledge-pure';

export function readKnowledgeTabFromLocation(searchParams: URLSearchParams): KnowledgeTabId {
  return normalizeKnowledgeTab(searchParams.get('tab')) ?? 'ingest';
}

export async function persistKnowledgeTabToUrl(currentUrl: URL, activeTab: KnowledgeTabId): Promise<void> {
  const nextUrl = new URL(currentUrl);
  if (activeTab === 'ingest') {
    nextUrl.searchParams.delete('tab');
  } else {
    nextUrl.searchParams.set('tab', activeTab);
  }

  const next = `${nextUrl.pathname}${nextUrl.search}`;
  const current = `${currentUrl.pathname}${currentUrl.search}`;
  if (next === current) return;

  await goto(next, {
    keepFocus: true,
    noScroll: true,
    replaceState: true
  });
}
