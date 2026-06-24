import { PREF_KEYS } from '$lib/preferences/keys';
import { createPersistentRecord } from '$lib/state/create-persistent-state.svelte';
import type { Codec } from '$lib/state/codecs';
import {
  decodeGraphOptionsRaw,
  encodeGraphOptions,
  GRAPH_OPTION_DEFAULTS,
  type GraphOptions
} from '../../graph/knowledge-graph-prefs';

export type GraphOptionsStateDeps = {
  /** Called when the global options reset also clears edge filters. */
  resetEdgeFilters: () => void;
};

const graphOptionsCodec: Codec<GraphOptions> = {
  decode: decodeGraphOptionsRaw,
  encode: (value) => encodeGraphOptions(value)
};

/** Reactive graph view options (sliders + focus modes), with localStorage persistence. */
export function createGraphOptionsState(deps: GraphOptionsStateDeps) {
  const options = createPersistentRecord({
    key: PREF_KEYS.knowledgeGraphOptions,
    tier: 'local',
    codec: graphOptionsCodec,
    defaults: GRAPH_OPTION_DEFAULTS
  });

  // Capture the record's own reset BEFORE Object.assign overwrites `options.reset` below —
  // otherwise the wrapper would call itself and recurse infinitely (stack overflow on reset).
  const resetOptions = options.reset;
  function reset(): void {
    resetOptions();
    deps.resetEdgeFilters();
  }

  return Object.assign(options, { reset });
}

export type GraphOptionsState = ReturnType<typeof createGraphOptionsState>;
