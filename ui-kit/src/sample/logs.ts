// The sample app's Logs page words: what an app gives the kit's Logs page ($hiro-app/logs).
import type { LogsApp } from '$kit/pages/logs/types';

export const LOGS: LogsApp = {
	name: 'Sample',
	sources: [
		{ value: 'sample', label: 'Sample' },
		{ value: 'crash', label: 'Crashes' }
	],
	areas: [
		['sample.gallery', 'Gallery'],
		['sample.app', 'Web server'],
		['crash', 'Crashes']
	],
	llm: { askers: ['Ask now', 'Other'], openLabel: (asker) => (asker === 'Ask now' ? 'the question' : 'the page') }
};
