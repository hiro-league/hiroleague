import { describe, expect, it } from 'vitest';
import { svgImage } from './svg';

const decode = (url: string) => decodeURIComponent(url.slice(url.indexOf(',') + 1));

describe('svgImage', () => {
	it('adds the namespace an image needs', () => {
		const url = svgImage('<svg width="105" height="105" class="segno"><path d="M2 2h7"/></svg>');
		expect(url.startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true);
		expect(decode(url)).toBe('<svg xmlns="http://www.w3.org/2000/svg" width="105" height="105" class="segno"><path d="M2 2h7"/></svg>');
	});
	it('keeps a namespace that is there', () => {
		const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>';
		expect(decode(svgImage(svg))).toBe(svg);
	});
	it('encodes what would end the address early', () => {
		expect(svgImage('<svg><text>#1 "a"</text></svg>')).not.toMatch(/[#"]/);
	});
});
