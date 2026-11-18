import { describe, expect, it } from 'vitest';
import { environmentOf } from './environment';

describe('environmentOf', () => {
	it('reads the environment from the port block', () => {
		expect(environmentOf('localhost', '7012')).toEqual({ kind: 'dev', n: 0 });
		expect(environmentOf('localhost', '7311')).toEqual({ kind: 'dev', n: 3 });
		expect(environmentOf('127.0.0.1', '7549')).toEqual({ kind: 'dev', n: 5 });
	});

	it('says live for a LAN name on port 80', () => {
		expect(environmentOf('reports.local', '')).toEqual({ kind: 'live' });
		expect(environmentOf('home.hiro.local', '')).toEqual({ kind: 'live' });
	});

	it('gives no badge elsewhere', () => {
		expect(environmentOf('localhost', '')).toBeNull();
		expect(environmentOf('localhost', '5173')).toBeNull();
		expect(environmentOf('localhost', '7350')).toBeNull(); // past the environment's 50 ports
		expect(environmentOf('127.0.0.1', '8120')).toBeNull();
	});
});
