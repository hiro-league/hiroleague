import { describe, expect, it } from 'vitest';
import type { CatalogModelRow } from '$lib/api/catalog';
import {
  allCatalogKinds,
  catalogHostingUiForRow,
  catalogKindsTitle,
  filterModelsByAvailability,
  isCatalogProviderOnline,
  isRowAvailable,
  listText,
  modelKindUiForRow,
  modelSupportsCatalogKind,
  parseCommaList
} from './catalog-filter-ui';

function model(p: Partial<CatalogModelRow> & Pick<CatalogModelRow, 'id' | 'provider_id' | 'display_name' | 'model_kind'>): CatalogModelRow {
  return { ...p };
}

describe('parseCommaList', () => {
  it('splits, trims, lowercases, and drops empties', () => {
    expect(parseCommaList(' Chat, TTS ,,embedding ')).toEqual(['chat', 'tts', 'embedding']);
  });
});

describe('allCatalogKinds', () => {
  it('dedupes primary and extra kinds in catalog order', () => {
    const row = model({
      id: 'm',
      provider_id: 'p',
      display_name: 'M',
      model_kind: 'chat',
      extra_kinds: ['tts', 'chat']
    });
    expect(allCatalogKinds(row)).toEqual(['chat', 'tts']);
  });
});

describe('modelSupportsCatalogKind', () => {
  it('matches primary or extra kinds', () => {
    const row = model({
      id: 'm',
      provider_id: 'p',
      display_name: 'M',
      model_kind: 'chat',
      extra_kinds: ['stt']
    });
    expect(modelSupportsCatalogKind(row, 'chat')).toBe(true);
    expect(modelSupportsCatalogKind(row, 'stt')).toBe(true);
    expect(modelSupportsCatalogKind(row, 'tts')).toBe(false);
  });
});

describe('catalogKindsTitle', () => {
  it('joins human-readable kind titles', () => {
    const row = model({
      id: 'm',
      provider_id: 'p',
      display_name: 'M',
      model_kind: 'chat',
      extra_kinds: ['tts']
    });
    expect(catalogKindsTitle(row)).toBe('Chat · Text-to-speech (TTS)');
  });
});

describe('modelKindUiForRow', () => {
  it('falls back to Box icon for unknown kinds', () => {
    const ui = modelKindUiForRow('custom');
    expect(ui.title).toBe('custom');
    expect(ui.Icon).toBeTruthy();
  });
});

describe('catalogHostingUiForRow', () => {
  it('maps known hosting values and unknown fallbacks', () => {
    expect(catalogHostingUiForRow('cloud').title).toBe('Cloud');
    expect(catalogHostingUiForRow('  LOCAL ').title).toBe('Local');
    expect(catalogHostingUiForRow('').title).toBe('Unknown hosting');
  });
});

describe('listText', () => {
  it('sorts and joins values or returns dash', () => {
    expect(listText(['b', 'a'])).toBe('a, b');
    expect(listText([])).toBe('-');
    expect(listText(undefined)).toBe('-');
  });
});

describe('isCatalogProviderOnline', () => {
  it('checks membership in configured provider ids', () => {
    const configured = new Set(['openai', 'anthropic']);
    expect(isCatalogProviderOnline('openai', configured)).toBe(true);
    expect(isCatalogProviderOnline('google', configured)).toBe(false);
  });
});

describe('isRowAvailable', () => {
  it('uses downloaded for local rows and provider config for cloud', () => {
    const configured = new Set(['openai']);
    expect(
      isRowAvailable(
        model({ id: 'l', provider_id: 'local', display_name: 'L', model_kind: 'chat', source: 'local', downloaded: true }),
        configured
      )
    ).toBe(true);
    expect(
      isRowAvailable(
        model({ id: 'l', provider_id: 'local', display_name: 'L', model_kind: 'chat', source: 'local', downloaded: false }),
        configured
      )
    ).toBe(false);
    expect(
      isRowAvailable(model({ id: 'c', provider_id: 'openai', display_name: 'C', model_kind: 'chat' }), configured)
    ).toBe(true);
  });
});

describe('filterModelsByAvailability', () => {
  const rows = [
    model({ id: 'on', provider_id: 'openai', display_name: 'On', model_kind: 'chat' }),
    model({ id: 'off', provider_id: 'missing', display_name: 'Off', model_kind: 'chat' })
  ];
  const configured = new Set(['openai']);

  it('returns all rows when no filter or both filters selected', () => {
    expect(filterModelsByAvailability(rows, [], configured)).toHaveLength(2);
    expect(filterModelsByAvailability(rows, ['online', 'offline'], configured)).toHaveLength(2);
  });

  it('filters to online or offline subsets', () => {
    expect(filterModelsByAvailability(rows, ['online'], configured).map((r) => r.id)).toEqual(['on']);
    expect(filterModelsByAvailability(rows, ['offline'], configured).map((r) => r.id)).toEqual(['off']);
  });
});
