import { describe, expect, it } from 'vitest';
import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';
import {
  inactiveProviderMessage,
  missingModelMessage,
  selectedModelIssue,
  type SelectedModelIssueInput
} from './selected-model-issue';

const models: CatalogModelRow[] = [
  { id: 'google:gemini-3.1-flash', provider_id: 'google', display_name: 'Gemini 3.1 Flash', model_kind: 'chat' },
  { id: 'openai:gpt-5-mini', provider_id: 'openai', display_name: 'GPT-5 mini', model_kind: 'chat' },
  { id: 'local:bge-small', provider_id: 'local', display_name: 'BGE small', model_kind: 'embedding', source: 'local' }
];

const providers = [
  { id: 'google', display_name: 'Google Gemini' },
  { id: 'openai', display_name: 'OpenAI' }
] as CatalogProviderRow[];

function input(over: Partial<SelectedModelIssueInput>): SelectedModelIssueInput {
  return {
    selectedId: 'google:gemini-3.1-flash',
    catalogModels: models,
    catalogLoaded: true,
    activeProviderIds: new Set(['google', 'openai', 'local']),
    activeProvidersResolved: true,
    providers,
    ...over
  };
}

describe('selectedModelIssue', () => {
  it('returns null for a catalog model whose provider is set up', () => {
    expect(selectedModelIssue(input({}))).toBeNull();
  });

  it('returns null when nothing is selected', () => {
    expect(selectedModelIssue(input({ selectedId: null }))).toBeNull();
    expect(selectedModelIssue(input({ selectedId: '' }))).toBeNull();
    expect(selectedModelIssue(input({ selectedId: '   ' }))).toBeNull();
  });

  it('flags a saved id that is no longer in the catalog', () => {
    expect(selectedModelIssue(input({ selectedId: 'google:gemini-3.5-flash' }))).toEqual({
      kind: 'missing',
      message: 'google:gemini-3.5-flash is no longer available. Pick another model.'
    });
  });

  it('flags a missing id even when the active-providers list has not loaded', () => {
    expect(
      selectedModelIssue(
        input({ selectedId: 'voyage:rerank-2.5', activeProvidersResolved: false, activeProviderIds: new Set() })
      )?.kind
    ).toBe('missing');
  });

  it('does not flag anything before the catalog has loaded', () => {
    expect(
      selectedModelIssue(input({ selectedId: 'google:gemini-3.5-flash', catalogModels: [], catalogLoaded: false }))
    ).toBeNull();
  });

  it('accepts local (downloadable) model rows as available', () => {
    expect(selectedModelIssue(input({ selectedId: 'local:bge-small' }))).toBeNull();
  });

  it('flags a model whose provider is not set up, naming the provider', () => {
    expect(selectedModelIssue(input({ activeProviderIds: new Set(['openai']) }))).toEqual({
      kind: 'provider_inactive',
      message: inactiveProviderMessage('Google Gemini')
    });
  });

  it('falls back to the provider id when the provider row is unknown', () => {
    expect(
      selectedModelIssue(input({ activeProviderIds: new Set(['google']), selectedId: 'openai:gpt-5-mini', providers: [] }))
        ?.message
    ).toBe(inactiveProviderMessage('openai'));
  });

  it('does not judge the provider until active providers have loaded', () => {
    expect(selectedModelIssue(input({ activeProviderIds: new Set(), activeProvidersResolved: false }))).toBeNull();
  });

  it('builds the missing message from the id', () => {
    expect(missingModelMessage('openai:gpt-4o-transcribe')).toBe(
      'openai:gpt-4o-transcribe is no longer available. Pick another model.'
    );
  });
});
