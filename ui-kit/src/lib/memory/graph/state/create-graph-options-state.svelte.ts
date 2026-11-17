import {
	GRAPH_OPTION_DEFAULTS,
	readGraphOptions,
	writeGraphOptions,
	type GraphOptions
} from '$kit/memory/graph/graph-prefs';

export type GraphOptionsStateDeps = {
	/** Called when the global options reset also clears edge filters. */
	resetEdgeFilters: () => void;
};

export type GraphOptionsState = GraphOptions & {
	/** Back to GRAPH_OPTION_DEFAULTS, and the edge filters to theirs. */
	reset(): void;
	snapshot(): GraphOptions;
};

/**
 * Reactive graph view options (sliders + focus modes), kept in this browser. Each field is a getter/setter pair, so
 * a panel can `bind:` to it; a set saves at once (no $effect, so it also works outside a component's start).
 */
export function createGraphOptionsState(deps: GraphOptionsStateDeps): GraphOptionsState {
	let record = $state<GraphOptions>(readGraphOptions());

	function persist(): void {
		writeGraphOptions(record);
	}

	const accessors: Record<string, unknown> = {
		reset(): void {
			record = { ...GRAPH_OPTION_DEFAULTS };
			persist();
			deps.resetEdgeFilters();
		},
		snapshot(): GraphOptions {
			return { ...record };
		}
	};

	for (const key of Object.keys(GRAPH_OPTION_DEFAULTS) as (keyof GraphOptions)[]) {
		Object.defineProperty(accessors, key, {
			enumerable: true,
			get() {
				return record[key];
			},
			set(next: GraphOptions[typeof key]) {
				record = { ...record, [key]: next };
				persist();
			}
		});
	}

	return accessors as GraphOptionsState;
}
