import type { CatalogModelRow } from '$lib/api/catalog';

/** TTS catalog table: $/1K input characters (script length), not tokens. */
export function formatTtsUsdPer1k(usd: number): string {
  if (!Number.isFinite(usd)) return '';
  return `$${usd.toFixed(3)}/1K characters`;
}

/** Read first numeric pricing field (handles camelCase if any proxy rewrites keys). */
export function pricingNum(pricing: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const raw = pricing[key];
    if (raw === undefined || raw === null) continue;
    const value = typeof raw === 'number' ? raw : Number(raw);
    if (Number.isFinite(value)) return value;
  }
  return null;
}

/**
 * USD per ~1k chars of script → speech for the catalog table.
 * Prefer catalog `estimated_usd_per_1k_chars_speech`; if missing (e.g. HiroServer not restarted after
 * PricingBlock schema change), derive from the same token assumptions as catalog.yaml.
 */
export function ttsUsdPer1kCatalogEstimate(
  model: CatalogModelRow,
  pricing: Record<string, unknown>
): number | null {
  const est = pricingNum(
    pricing,
    'estimated_usd_per_1k_chars_speech',
    'estimatedUsdPer1kCharsSpeech'
  );
  if (est !== null && est >= 0) return est;

  const input = pricingNum(pricing, 'input_per_1m_tokens');
  const output = pricingNum(pricing, 'output_per_1m_tokens');
  if (input === null && output !== null) {
    return output / 1000;
  }
  const textTokPer1k = 1000 / 4;
  if (model.provider_id === 'openai' && input !== null && output !== null) {
    return textTokPer1k * (input / 1_000_000 + 6 * (output / 1_000_000));
  }
  if (input !== null && output !== null) {
    const audioTokPer1kChars = (1000 / 14) * 25;
    return textTokPer1k * (input / 1_000_000) + audioTokPer1kChars * (output / 1_000_000);
  }
  return null;
}

export function modelPricing(model: CatalogModelRow): string {
  // Local in-process models cost nothing to run — state it explicitly rather than blank.
  if (model.free || model.source === 'local') return 'Free';
  const pricing = model.pricing;
  if (!pricing || typeof pricing !== 'object') return '-';

  const num = (key: string) => {
    const raw = pricing[key];
    if (raw === undefined || raw === null) return null;
    const value = typeof raw === 'number' ? raw : Number(raw);
    return Number.isFinite(value) ? value : null;
  };

  if (model.model_kind === 'chat') {
    const input = num('input_per_1m_tokens');
    const output = num('output_per_1m_tokens');
    if (input !== null || output !== null) {
      return [
        input !== null ? `$${input.toFixed(2)}/1M in` : '',
        output !== null ? `$${output.toFixed(2)}/1M out` : ''
      ]
        .filter(Boolean)
        .join(' / ');
    }
  }
  if (model.model_kind === 'embedding') {
    const input = num('input_per_1m_tokens');
    if (input !== null) return `$${input.toFixed(2)}/1M tokens`;
  }
  if (model.model_kind === 'image_gen') {
    const input = num('input_per_1m_tokens');
    const output = num('output_per_1m_tokens');
    if (input !== null || output !== null) {
      return [
        input !== null ? `$${input.toFixed(2)}/1M in` : '',
        output !== null ? `$${output.toFixed(2)}/1M out` : ''
      ]
        .filter(Boolean)
        .join(' / ');
    }
  }
  if (model.model_kind === 'tts') {
    const est = ttsUsdPer1kCatalogEstimate(model, pricing as Record<string, unknown>);
    if (est !== null && Number.isFinite(est)) return formatTtsUsdPer1k(est);
    return '-';
  }
  if (model.model_kind === 'stt') {
    const perSecond = num('per_second');
    if (perSecond !== null) return `$${perSecond.toFixed(4)}/sec audio`;
  }
  if (model.model_kind === 'rerank') {
    // Cohere only — Voyage rows include estimated_usd_per_1k_searches: null in the API payload.
    const per1kSearches = num('estimated_usd_per_1k_searches');
    if (per1kSearches !== null && model.provider_id === 'cohere') {
      return `$${per1kSearches.toFixed(2)}/1K searches`;
    }
    const estReq = num('estimated_usd_per_request');
    let per1kProcessed = num('per_1k_tokens');
    if (per1kProcessed === null) {
      const per1m = num('input_per_1m_tokens');
      if (per1m !== null) per1kProcessed = per1m / 1000;
    }
    const lines: string[] = [];
    if (per1kProcessed !== null) {
      lines.push(`$${per1kProcessed.toFixed(5)}/1K processed tokens`);
    }
    if (estReq !== null) {
      lines.push(`~$${estReq.toFixed(4)}/request (est.)`);
    }
    if (lines.length > 0) return lines.join('\n');
  }
  return '-';
}

/** Build https URL from catalog `pricing.pricing_source` (often host/path; YAML may append notes in parentheses). */
export function pricingSourceHref(model: CatalogModelRow): string | null {
  const pricing = model.pricing;
  if (!pricing || typeof pricing !== 'object') return null;
  const raw = pricing['pricing_source'];
  if (typeof raw !== 'string') return null;
  let s = raw.trim();
  if (!s) return null;
  const paren = s.indexOf(' (');
  if (paren !== -1) s = s.slice(0, paren).trim();
  if (!s) return null;
  if (/^https?:\/\//i.test(s)) return s;
  if (s.startsWith('//')) return `https:${s}`;
  if (/^[a-z0-9][a-z0-9+.-]*\.[a-z]{2,}/i.test(s)) {
    return `https://${s.replace(/^\/+/, '')}`;
  }
  return null;
}
