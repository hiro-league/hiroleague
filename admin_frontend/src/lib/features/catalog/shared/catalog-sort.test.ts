import { describe, expect, it } from 'vitest';
import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';
import { sortModels, sortProviders } from './catalog-sort';

function provider(p: Partial<CatalogProviderRow> & Pick<CatalogProviderRow, 'id' | 'display_name' | 'hosting'>): CatalogProviderRow {
  return { ...p };
}

function model(p: Partial<CatalogModelRow> & Pick<CatalogModelRow, 'id' | 'provider_id' | 'display_name' | 'model_kind'>): CatalogModelRow {
  return { ...p };
}

describe('sortProviders', () => {
  const configured = new Set(['alpha']);

  it('sorts by display name ascending by default', () => {
    const rows = [
      provider({ id: 'b', display_name: 'Beta', hosting: 'cloud' }),
      provider({ id: 'a', display_name: 'Alpha', hosting: 'cloud' })
    ];
    expect(sortProviders(rows, 'provider', 'asc', configured).map((r) => r.id)).toEqual(['a', 'b']);
  });

  it('sorts online providers first when sortBy is online desc', () => {
    const onlineConfigured = new Set(['on']);
    const rows = [
      provider({ id: 'off', display_name: 'Off', hosting: 'cloud' }),
      provider({ id: 'on', display_name: 'On', hosting: 'cloud' })
    ];
    expect(sortProviders(rows, 'online', 'desc', onlineConfigured).map((r) => r.id)).toEqual(['on', 'off']);
  });
});

describe('sortModels', () => {
  const configured = new Set(['openai']);
  const labels = { openai: 'OpenAI', anthropic: 'Anthropic' };

  it('sorts by provider label', () => {
    const rows = [
      model({ id: 'a', provider_id: 'anthropic', display_name: 'A', model_kind: 'chat' }),
      model({ id: 'o', provider_id: 'openai', display_name: 'O', model_kind: 'chat' })
    ];
    expect(sortModels(rows, 'provider', 'asc', labels, configured).map((r) => r.id)).toEqual(['a', 'o']);
  });

  it('sorts by context window numerically', () => {
    const rows = [
      model({ id: 'big', provider_id: 'p', display_name: 'Big', model_kind: 'chat', context_window: 128000 }),
      model({ id: 'small', provider_id: 'p', display_name: 'Small', model_kind: 'chat', context_window: 8000 })
    ];
    expect(sortModels(rows, 'context', 'asc', labels, configured).map((r) => r.id)).toEqual(['small', 'big']);
  });

  it('sorts by primary catalog kind', () => {
    const rows = [
      model({ id: 'tts', provider_id: 'p', display_name: 'T', model_kind: 'tts' }),
      model({ id: 'chat', provider_id: 'p', display_name: 'C', model_kind: 'chat', extra_kinds: ['stt'] })
    ];
    expect(sortModels(rows, 'kind', 'asc', labels, configured).map((r) => r.id)).toEqual(['chat', 'tts']);
  });

  it('puts available models first when sorting by online desc', () => {
    const rows = [
      model({ id: 'off', provider_id: 'missing', display_name: 'Off', model_kind: 'chat' }),
      model({ id: 'on', provider_id: 'openai', display_name: 'On', model_kind: 'chat' })
    ];
    expect(sortModels(rows, 'online', 'desc', labels, configured).map((r) => r.id)).toEqual(['on', 'off']);
  });
});
