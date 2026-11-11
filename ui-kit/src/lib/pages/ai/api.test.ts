import { describe, expect, it } from 'vitest';
import { coreEditUrl, coreProfilesUrl } from '$kit/pages/ai/api';

describe('links into the core admin', () => {
	it('open the AI or voice profiles, and one profile editor', () => {
		expect(coreProfilesUrl('http://core', 'ai')).toBe('http://core/catalog/?tab=profiles');
		expect(coreProfilesUrl('http://core', 'voice')).toBe('http://core/catalog/?tab=voices');
		expect(coreEditUrl('http://core', 'ai', 'a b')).toBe('http://core/catalog/?tab=profiles&edit=a%20b');
	});
	it('are empty while the admin address is unknown', () => {
		expect(coreProfilesUrl(undefined, 'ai')).toBe('');
		expect(coreEditUrl('', 'voice', 'x')).toBe('');
	});
});
