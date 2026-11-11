import { describe, expect, it } from 'vitest';
import type { CoreProfile, CoreUse } from '$kit/pages/ai/api';
import { budgetHint, chainLine, fallbacksOf, needLabels, usageText } from '$kit/hiroleague/core-ai';

const P = (p: Partial<CoreProfile> & { id: string }): CoreProfile => ({
	name: p.id,
	kind: 'api',
	provider: 'Google',
	model: 'Gemini 3.8 Flash',
	model_id: 'google:gemini-3.8-flash',
	sent_to: 'Google',
	...p
});
const PROFILES: CoreProfile[] = [
	P({ id: 'camera', name: 'Camera questions', max_cost_day: 1, at_once: 2, fallback_id: 'camera-codex', spent_today: 0.34, asks_today: 41 }),
	P({ id: 'camera-codex', name: 'Camera on Codex', kind: 'plan', provider: 'Codex', max_per_hour: 30, fallback_id: 'local-vision', this_hour: 2 }),
	P({ id: 'local-vision', name: 'Local vision', kind: 'local', max_per_hour: 60 }),
	P({ id: 'homework', name: 'Homework reviews', kind: 'plan', max_per_hour: 10, this_hour: 3 }),
	P({ id: 'short', name: 'Short texts', max_cost_day: 0.5 })
];
const byId = (id: string) => PROFILES.find((p) => p.id === id)!;
const USE: CoreUse = { id: 'ask', name: 'Ask a camera', needs: ['pictures', 'json'], pictures_up_to: 2, profile_id: 'camera', chain: ['camera', 'camera-codex', 'local-vision'] };

describe('core AI words', () => {
	it("says a budget the way its provider counts it, or in the core's own words", () => {
		expect(budgetHint(byId('camera'))).toBe('up to $1.00 a day, 2 at once');
		expect(budgetHint(byId('camera-codex'))).toBe('30 an hour');
		expect(budgetHint({ ...byId('short'), max_cost_day: null })).toBe('no daily limit');
		expect(budgetHint({ ...byId('short'), budget: '$0.50 a day (the home’s day)' })).toBe('$0.50 a day (the home’s day)');
	});

	it("says today's use", () => {
		expect(usageText(byId('camera'))).toBe('$0.34 of $1.00 today, 41 asks');
		expect(usageText(byId('homework'))).toBe('3 of 10 this hour');
		expect(usageText(byId('short'))).toBe('');
	});

	it("draws a use's chain as the core reports it", () => {
		expect(chainLine(USE, PROFILES)).toBe('Camera questions → Camera on Codex → Local vision');
		expect(chainLine({ ...USE, chain: ['short', 'gone'] }, PROFILES)).toBe('Short texts → a missing profile');
		expect(chainLine({ ...USE, chain: undefined }, PROFILES)).toBe('');
	});

	it("follows a profile's chain, else its fallbacks at most three deep, stopping at a loop", () => {
		expect(fallbacksOf('camera', PROFILES).map((p) => p.id)).toEqual(['camera', 'camera-codex', 'local-vision']);
		expect(fallbacksOf('camera', [{ ...byId('camera'), chain: ['camera', 'short'] }, byId('short')]).map((p) => p.id)).toEqual(['camera', 'short']);
		const loop = [P({ id: 'a', fallback_id: 'b' }), P({ id: 'b', fallback_id: 'a' })];
		expect(fallbacksOf('a', loop).map((p) => p.id)).toEqual(['a', 'b']);
		expect(fallbacksOf('nope', PROFILES)).toEqual([]);
	});

	it('names what a use sends', () => {
		expect(needLabels({ ...USE, id: 'study', pictures_up_to: 60 }).map((n) => n.label)).toEqual(['Up to 60 pictures', 'JSON']);
		expect(needLabels({ ...USE, needs: ['sound', 'json'], pictures_up_to: null }).map((n) => n.label)).toEqual(['A sound', 'JSON']);
		expect(needLabels({ ...USE, pictures_up_to: null }).map((n) => n.label)).toEqual(['Pictures', 'JSON']);
	});
});
