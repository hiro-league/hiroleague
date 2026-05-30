import {
  ArrowDownWideNarrow,
  Box,
  Cloud,
  Image as ImageIcon,
  Layers,
  MessageSquare,
  Mic,
  Server,
  Volume2
} from '@lucide/svelte';
import type { CatalogModelRow } from '$lib/api/catalog';

export const MODEL_KIND_FILTER_IDS = ['chat', 'tts', 'stt', 'embedding', 'image_gen', 'rerank'] as const;
export type ModelKindFilterId = (typeof MODEL_KIND_FILTER_IDS)[number];

export const HOSTING_FILTER_IDS = ['cloud', 'local'] as const;
export type HostingFilterId = (typeof HOSTING_FILTER_IDS)[number];

export const AVAILABILITY_FILTER_IDS = ['online', 'offline'] as const;
export type AvailabilityFilterId = (typeof AVAILABILITY_FILTER_IDS)[number];

export const MODEL_KIND_FILTER_UI: Record<
  ModelKindFilterId,
  { Icon: typeof MessageSquare; title: string }
> = {
  chat: { Icon: MessageSquare, title: 'Chat' },
  tts: { Icon: Volume2, title: 'Text-to-speech (TTS)' },
  stt: { Icon: Mic, title: 'Speech-to-text (STT)' },
  embedding: { Icon: Layers, title: 'Embedding' },
  image_gen: { Icon: ImageIcon, title: 'Image generation' },
  rerank: { Icon: ArrowDownWideNarrow, title: 'Reranker' }
};

export const HOSTING_FILTER_UI: Record<
  HostingFilterId,
  { Icon: typeof Cloud; title: string }
> = {
  cloud: { Icon: Cloud, title: 'Cloud' },
  local: { Icon: Server, title: 'Local' }
};

export const AVAILABILITY_FILTER_UI: Record<
  AvailabilityFilterId,
  { title: string; circleClass: string }
> = {
  online: {
    title: 'Online — provider configured in this workspace',
    circleClass: 'bg-green-600 dark:bg-green-500'
  },
  offline: {
    title: 'Offline — provider not configured in this workspace',
    circleClass: 'bg-muted-foreground/40'
  }
};

export const MODEL_CLASS_OPTIONS = ['', 'agentic', 'fast', 'balanced', 'reasoning', 'creative', 'coding'];

export function parseCommaList(raw: string): string[] {
  return raw
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

export function modelKindUiForRow(kind: string) {
  const k = kind as ModelKindFilterId;
  if (k in MODEL_KIND_FILTER_UI) {
    return MODEL_KIND_FILTER_UI[k];
  }
  return { Icon: Box, title: kind };
}

/** Distinct kinds for this row (primary first, then extras), in catalog kind order. */
export function allCatalogKinds(model: CatalogModelRow): ModelKindFilterId[] {
  const primary = model.model_kind;
  const extras = model.extra_kinds ?? [];
  const raw = [primary, ...extras];
  const uniq = [...new Set(raw)];
  const order = [...MODEL_KIND_FILTER_IDS] as string[];
  return uniq.sort((a, b) => order.indexOf(a) - order.indexOf(b)) as ModelKindFilterId[];
}

export function modelSupportsCatalogKind(model: CatalogModelRow, kind: string): boolean {
  if (model.model_kind === kind) return true;
  return (model.extra_kinds ?? []).includes(kind);
}

export function catalogKindsTitle(model: CatalogModelRow): string {
  return allCatalogKinds(model)
    .map((k) => modelKindUiForRow(k).title)
    .join(' · ');
}

export function catalogHostingUiForRow(hosting: string | null | undefined) {
  const h = (hosting ?? '').trim().toLowerCase() as HostingFilterId;
  if (h in HOSTING_FILTER_UI) {
    return HOSTING_FILTER_UI[h];
  }
  return { Icon: Box, title: hosting?.trim() ? hosting : 'Unknown hosting' };
}

export function listText(values: string[] | undefined) {
  return values?.length ? values.slice().sort().join(', ') : '-';
}

export function isCatalogProviderOnline(providerId: string, configuredProviderIds: Set<string>): boolean {
  return configuredProviderIds.has(providerId);
}

/** Availability for a browse row. Cloud/server rows: provider configured. Local rows: downloaded. */
export function isRowAvailable(
  model: CatalogModelRow,
  configuredProviderIds: Set<string>
): boolean {
  if (model.source === 'local') return Boolean(model.downloaded);
  return isCatalogProviderOnline(model.provider_id, configuredProviderIds);
}

export function filterModelsByAvailability(
  rows: CatalogModelRow[],
  selected: AvailabilityFilterId[],
  configuredProviderIds: Set<string>
): CatalogModelRow[] {
  if (selected.length === 0 || selected.length === AVAILABILITY_FILTER_IDS.length) {
    return rows;
  }
  const wantOnline = selected.includes('online');
  const wantOffline = selected.includes('offline');
  return rows.filter((model) => {
    const online = isRowAvailable(model, configuredProviderIds);
    return (online && wantOnline) || (!online && wantOffline);
  });
}
