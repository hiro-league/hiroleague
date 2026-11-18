import { describe, expect, it } from 'vitest';
import { inBannerOrder, placeOf } from './place';

describe('the place in who-is-asking', () => {
	it('is none in live, in env0, and for an app whose answer has none', () => {
		expect(placeOf(null)).toBeNull();
		expect(placeOf({ name: 'Michel' })).toBeNull();
		expect(placeOf({ name: 'Michel', place: null })).toBeNull();
	});

	it('is the test environment the backend says', () => {
		expect(placeOf({ place: { place: 'env2', preset: 'Safe' } })?.place).toBe('env2');
	});

	it('shows the real systems first', () => {
		const place = { place: 'env2', preset: 'AI', systems: [
			{ id: 'ha', name: 'Home Assistant', mode: 'read' as const },
			{ id: 'ai', name: 'AI', mode: 'real' as const }
		] };
		expect(inBannerOrder(place).map((s) => s.id)).toEqual(['ai', 'ha']);
	});
});
