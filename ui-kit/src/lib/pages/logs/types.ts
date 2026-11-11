// What an app tells the Logs page about itself ($hiro-app/logs): its log sources and logger areas, and whether it
// has an LLM requests tab. Everything else on the page is the same in every app.

export type LogsApp = {
	/** The app's name in the page's words ("What HomeHiro did"). */
	name: string;
	/** What the "From" filter offers: the app's own source and the crashes, after "All sources". */
	sources: { value: string; label: string }[];
	/** Logger name (or its start) -> the area, in words. */
	areas: [prefix: string, area: string][];
	/** The LLM requests tab; null when the app asks no AI. */
	llm: null | {
		/** The kinds of asker the filter offers, after "All". */
		askers: string[];
		/** Where the link of a request goes, in words ("Open the question"). */
		openLabel: (asker: string) => string;
	};
};
