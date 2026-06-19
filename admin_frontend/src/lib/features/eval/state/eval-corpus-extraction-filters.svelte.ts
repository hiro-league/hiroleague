import type { CorpusEpisodeExtraction } from '$lib/api/eval';
import {
  extractionMaxCounts,
  type CorpusExtractionFilterState
} from '$lib/features/eval/shared/eval-corpus-review-pure';

/** Extraction count filters for the Corpus review toolbar (entity/fact ranges + no-extraction). */
export function createCorpusExtractionFilters(
  getExtraction: () => Record<string, CorpusEpisodeExtraction> | undefined
) {
  let noExtractionOnly = $state(false);
  let entRange = $state<[number, number] | null>(null);
  let factRange = $state<[number, number] | null>(null);

  $effect(() => {
    getExtraction();
    noExtractionOnly = false;
    entRange = null;
    factRange = null;
  });

  const extraction = $derived(getExtraction());
  const { maxEnt, maxFact } = $derived(extractionMaxCounts(extraction));
  const hasExtraction = $derived(!!extraction && Object.keys(extraction).length > 0);
  const entActive = $derived(!!entRange && (entRange[0] > 0 || entRange[1] < maxEnt));
  const factActive = $derived(!!factRange && (factRange[0] > 0 || factRange[1] < maxFact));
  const countFilterActive = $derived(noExtractionOnly || entActive || factActive);

  const filterState = $derived<CorpusExtractionFilterState>({
    noExtractionOnly,
    entRange,
    factRange,
    entActive,
    factActive
  });

  function reset() {
    noExtractionOnly = false;
    entRange = null;
    factRange = null;
  }

  return {
    get noExtractionOnly() {
      return noExtractionOnly;
    },
    set noExtractionOnly(v: boolean) {
      noExtractionOnly = v;
    },
    get entRange() {
      return entRange;
    },
    set entRange(v: [number, number] | null) {
      entRange = v;
    },
    get factRange() {
      return factRange;
    },
    set factRange(v: [number, number] | null) {
      factRange = v;
    },
    get maxEnt() {
      return maxEnt;
    },
    get maxFact() {
      return maxFact;
    },
    get hasExtraction() {
      return hasExtraction;
    },
    get countFilterActive() {
      return countFilterActive;
    },
    get filterState() {
      return filterState;
    },
    reset
  };
}

export type CorpusExtractionFilters = ReturnType<typeof createCorpusExtractionFilters>;
