import type { CorpusEpisodeExtraction, EvalEpisode } from '$lib/api/eval';

/** Collapsed episode bodies clamp to this many text lines until expanded. */
export const CORPUS_CLAMP_LINES = 6;
/** Approx characters-per-line for clamp heuristic (tune alongside CORPUS_CLAMP_LINES). */
export const CORPUS_CHARS_PER_LINE = 88;
export const CORPUS_CLAMP_CHARS = CORPUS_CLAMP_LINES * CORPUS_CHARS_PER_LINE;
export const CORPUS_CLAMP_MAX_HEIGHT = `${CORPUS_CLAMP_LINES * 1.5}rem`;

export type CorpusExtractionFilterState = {
  noExtractionOnly: boolean;
  entRange: [number, number] | null;
  factRange: [number, number] | null;
  entActive: boolean;
  factActive: boolean;
};

/** 1-based episode position in the full corpus (stable regardless of filter). */
export function buildEpisodeNoMap(episodes: EvalEpisode[]): Map<string, number> {
  const m = new Map<string, number>();
  episodes.forEach((ep, i) => m.set(ep.id, i + 1));
  return m;
}

export function extractionMaxCounts(extraction: Record<string, CorpusEpisodeExtraction> | undefined): {
  maxEnt: number;
  maxFact: number;
} {
  const values = extraction ? Object.values(extraction) : [];
  return {
    maxEnt: values.reduce((m, x) => Math.max(m, x.entity_count), 0),
    maxFact: values.reduce((m, x) => Math.max(m, x.fact_count), 0)
  };
}

export function isCorpusExtractionFilterActive(state: CorpusExtractionFilterState): boolean {
  return state.noExtractionOnly || state.entActive || state.factActive;
}

/** Search + optional extraction count filters (AND together). */
export function filterCorpusEpisodes(
  episodes: EvalEpisode[],
  search: string,
  extraction: Record<string, CorpusEpisodeExtraction> | undefined,
  state: CorpusExtractionFilterState,
  maxEnt: number,
  maxFact: number
): EvalEpisode[] {
  const term = search.trim().toLowerCase();
  let list = term
    ? episodes.filter((ep) => `${ep.body} ${ep.speaker} ${ep.id}`.toLowerCase().includes(term))
    : episodes;
  if (!extraction || !isCorpusExtractionFilterActive(state)) return list;

  const [eLo, eHi] = state.entRange ?? [0, maxEnt];
  const [fLo, fHi] = state.factRange ?? [0, maxFact];
  list = list.filter((ep) => {
    const x = extraction[ep.id];
    if (!x) return false;
    if (state.noExtractionOnly && !(x.entity_count === 0 && x.fact_count === 0)) return false;
    if (state.entActive && (x.entity_count < eLo || x.entity_count > eHi)) return false;
    if (state.factActive && (x.fact_count < fLo || x.fact_count > fHi)) return false;
    return true;
  });
  return list;
}

export function corpusEpisodeNeedsClamp(ep: EvalEpisode): boolean {
  return ep.body.length > CORPUS_CLAMP_CHARS || ep.body.split('\n').length > CORPUS_CLAMP_LINES;
}

/** Current episode = last one whose top crossed the sticky anchor line. */
export function corpusScrollAnchorEpisodeId(
  filtered: EvalEpisode[],
  nodes: ReadonlyMap<string, HTMLElement>,
  anchorTop: number
): string | null {
  let cur: string | null = filtered[0]?.id ?? null;
  for (const ep of filtered) {
    const n = nodes.get(ep.id);
    if (!n) continue;
    if (n.getBoundingClientRect().top <= anchorTop) cur = ep.id;
    else break;
  }
  return cur;
}
