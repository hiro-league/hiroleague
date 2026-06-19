import { describe, it, expect } from 'vitest';
import { trackConfig } from './eval-tracks';

describe('trackConfig', () => {
  it('returns the matching track in each config', () => {
    expect(trackConfig('memory').track).toBe('memory');
    expect(trackConfig('knowledge').track).toBe('knowledge');
    expect(trackConfig('memory').label).toBe('Memory');
    expect(trackConfig('knowledge').label).toBe('Knowledge');
  });

  it('memory carries the recall/evidence/verdict columns; knowledge carries Δ', () => {
    const m = trackConfig('memory');
    const k = trackConfig('knowledge');
    expect(m.showRecallColumn).toBe(true);
    expect(m.showEvidenceColumn).toBe(true);
    expect(m.showAnswerTypeColumn).toBe(true);
    expect(m.showDelta).toBe(false);
    expect(k.showDelta).toBe(true);
    expect(k.showRecallColumn).toBe(false);
    expect(k.showEvidenceColumn).toBe(false);
    expect(k.showAnswerTypeColumn).toBe(false);
  });

  it('memory owns ingestion/persistence/benchmark/corpus affordances', () => {
    const m = trackConfig('memory');
    const k = trackConfig('knowledge');
    for (const flag of [
      'hasCorpusReview',
      'hasBenchmarks',
      'tracksIngestion',
      'persistsResults',
      'canExportLocomo',
      'hasEpisodeWindow',
      'hasQuestionConcurrency',
      'hasAnswerPrompt'
    ] as const) {
      expect(m[flag], `memory.${flag}`).toBe(true);
      expect(k[flag], `knowledge.${flag}`).toBe(false);
    }
  });

  it('the leg selector is knowledge-only (memory is a single recall leg)', () => {
    expect(trackConfig('knowledge').hasLegSelector).toBe(true);
    expect(trackConfig('memory').hasLegSelector).toBe(false);
  });

  it('exposes distinct ingest hints and clear labels per track', () => {
    expect(trackConfig('memory').clearLabel).toBe('Clear results');
    expect(trackConfig('knowledge').clearLabel).toBe('Clear');
    expect(trackConfig('memory').ingestHint).not.toBe(trackConfig('knowledge').ingestHint);
  });
});
