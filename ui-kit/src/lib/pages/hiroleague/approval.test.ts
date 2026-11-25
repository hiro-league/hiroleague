import { describe, expect, it } from 'vitest';
import { waitingLine } from './approval';

describe('waitingLine', () => {
	it('reads as a sentence, naming its subject where it has one', () => {
		expect(waitingLine({ permission: 'ai.search', words: 'use the search models: turn texts into vectors and rank them' })).toBe(
			'Use the search models: turn texts into vectors and rank them.'
		);
		expect(waitingLine({ permission: 'apps.ask', subject: 'net', words: 'ask another app for its data' })).toBe('Ask another app for its data (net).');
		expect(waitingLine({ permission: 'people.see', subject: '', words: 'read the people list' })).toBe('Read the people list.');
	});
});
