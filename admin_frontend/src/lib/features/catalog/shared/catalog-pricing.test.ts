import { describe, expect, it } from 'vitest';
import type { CatalogModelRow } from '$lib/api/catalog';
import {
  formatTtsUsdPer1k,
  modelPricing,
  pricingNum,
  pricingSourceHref,
  ttsUsdPer1kCatalogEstimate
} from './catalog-pricing';

function model(p: Partial<CatalogModelRow> & Pick<CatalogModelRow, 'id' | 'provider_id' | 'display_name' | 'model_kind'>): CatalogModelRow {
  return {
    ...p
  };
}

describe('formatTtsUsdPer1k', () => {
  it('formats finite USD values to three decimals', () => {
    expect(formatTtsUsdPer1k(0.015)).toBe('$0.015/1K characters');
    expect(formatTtsUsdPer1k(1.2)).toBe('$1.200/1K characters');
  });

  it('returns empty string for non-finite values', () => {
    expect(formatTtsUsdPer1k(Number.NaN)).toBe('');
    expect(formatTtsUsdPer1k(Number.POSITIVE_INFINITY)).toBe('');
  });
});

describe('pricingNum', () => {
  it('reads the first finite numeric field across key aliases', () => {
    expect(pricingNum({ input_per_1m_tokens: 3 }, 'input_per_1m_tokens')).toBe(3);
    expect(pricingNum({ estimatedUsdPer1kCharsSpeech: '0.5' }, 'estimated_usd_per_1k_chars_speech', 'estimatedUsdPer1kCharsSpeech')).toBe(0.5);
  });

  it('returns null when no keys match or values are invalid', () => {
    expect(pricingNum({}, 'missing')).toBeNull();
    expect(pricingNum({ x: 'nope' }, 'x')).toBeNull();
    expect(pricingNum({ x: null }, 'x')).toBeNull();
  });
});

describe('ttsUsdPer1kCatalogEstimate', () => {
  it('prefers catalog estimated_usd_per_1k_chars_speech when present', () => {
    const row = model({ id: 't', provider_id: 'openai', display_name: 'T', model_kind: 'tts' });
    expect(
      ttsUsdPer1kCatalogEstimate(row, { estimated_usd_per_1k_chars_speech: 0.042 })
    ).toBe(0.042);
  });

  it('derives from output-only pricing as output/1000', () => {
    const row = model({ id: 't', provider_id: 'x', display_name: 'T', model_kind: 'tts' });
    expect(ttsUsdPer1kCatalogEstimate(row, { output_per_1m_tokens: 5000 })).toBe(5);
  });

  it('uses OpenAI token assumptions when both input and output are set', () => {
    const row = model({ id: 't', provider_id: 'openai', display_name: 'T', model_kind: 'tts' });
    const est = ttsUsdPer1kCatalogEstimate(row, {
      input_per_1m_tokens: 1_000_000,
      output_per_1m_tokens: 1_000_000
    });
    // textTokPer1k=250; input/1M + 6*output/1M = 250 + 1500 = 1750
    expect(est).toBeCloseTo(1750, 5);
  });

  it('uses generic audio token assumptions for non-OpenAI providers', () => {
    const row = model({ id: 't', provider_id: 'elevenlabs', display_name: 'T', model_kind: 'tts' });
    const est = ttsUsdPer1kCatalogEstimate(row, {
      input_per_1m_tokens: 1_000_000,
      output_per_1m_tokens: 1_000_000
    });
    expect(est).not.toBeNull();
    expect(est!).toBeGreaterThan(0);
  });

  it('returns null when pricing is insufficient', () => {
    const row = model({ id: 't', provider_id: 'x', display_name: 'T', model_kind: 'tts' });
    expect(ttsUsdPer1kCatalogEstimate(row, {})).toBeNull();
  });
});

describe('modelPricing', () => {
  it('shows Free for free or local models', () => {
    expect(modelPricing(model({ id: 'a', provider_id: 'p', display_name: 'A', model_kind: 'chat', free: true }))).toBe('Free');
    expect(modelPricing(model({ id: 'a', provider_id: 'p', display_name: 'A', model_kind: 'chat', source: 'local' }))).toBe('Free');
  });

  it('formats chat and image_gen token pricing', () => {
    const chat = model({
      id: 'c',
      provider_id: 'p',
      display_name: 'C',
      model_kind: 'chat',
      pricing: { input_per_1m_tokens: 1.5, output_per_1m_tokens: 6 }
    });
    expect(modelPricing(chat)).toBe('$1.50/1M in / $6.00/1M out');
  });

  it('formats embedding input pricing', () => {
    const emb = model({
      id: 'e',
      provider_id: 'p',
      display_name: 'E',
      model_kind: 'embedding',
      pricing: { input_per_1m_tokens: 0.1 }
    });
    expect(modelPricing(emb)).toBe('$0.10/1M tokens');
  });

  it('formats TTS via catalog estimate', () => {
    const tts = model({
      id: 't',
      provider_id: 'p',
      display_name: 'T',
      model_kind: 'tts',
      pricing: { estimated_usd_per_1k_chars_speech: 0.02 }
    });
    expect(modelPricing(tts)).toBe('$0.020/1K characters');
  });

  it('formats STT per-second pricing', () => {
    const stt = model({
      id: 's',
      provider_id: 'p',
      display_name: 'S',
      model_kind: 'stt',
      pricing: { per_second: 0.0003 }
    });
    expect(modelPricing(stt)).toBe('$0.0003/sec audio');
  });

  it('formats Cohere rerank per-1k-searches', () => {
    const rerank = model({
      id: 'r',
      provider_id: 'cohere',
      display_name: 'R',
      model_kind: 'rerank',
      pricing: { estimated_usd_per_1k_searches: 2 }
    });
    expect(modelPricing(rerank)).toBe('$2.00/1K searches');
  });

  it('returns dash when pricing is missing', () => {
    expect(modelPricing(model({ id: 'x', provider_id: 'p', display_name: 'X', model_kind: 'chat' }))).toBe('-');
  });
});

describe('pricingSourceHref', () => {
  it('normalizes bare domains and strips parenthetical notes', () => {
    const row = model({
      id: 'm',
      provider_id: 'p',
      display_name: 'M',
      model_kind: 'chat',
      pricing: { pricing_source: 'openai.com/pricing (as of 2024)' }
    });
    expect(pricingSourceHref(row)).toBe('https://openai.com/pricing');
  });

  it('passes through absolute https URLs', () => {
    const row = model({
      id: 'm',
      provider_id: 'p',
      display_name: 'M',
      model_kind: 'chat',
      pricing: { pricing_source: 'https://example.com/rates' }
    });
    expect(pricingSourceHref(row)).toBe('https://example.com/rates');
  });

  it('returns null for empty or invalid sources', () => {
    expect(pricingSourceHref(model({ id: 'm', provider_id: 'p', display_name: 'M', model_kind: 'chat' }))).toBeNull();
    expect(
      pricingSourceHref(
        model({
          id: 'm',
          provider_id: 'p',
          display_name: 'M',
          model_kind: 'chat',
          pricing: { pricing_source: 'not a url' }
        })
      )
    ).toBeNull();
  });
});
