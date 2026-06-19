import { describe, expect, it } from 'vitest';
import {
  composeImagePrompt,
  estimateImageCostUsd,
  isValidImageProfileId,
  parseImageSeed
} from './image-lab-pure';

describe('isValidImageProfileId', () => {
  it('accepts lowercase slug ids', () => {
    expect(isValidImageProfileId('my_recipe')).toBe(true);
    expect(isValidImageProfileId('a2')).toBe(true);
  });

  it('rejects invalid slugs', () => {
    expect(isValidImageProfileId('')).toBe(false);
    expect(isValidImageProfileId('My-Recipe')).toBe(false);
    expect(isValidImageProfileId('_bad')).toBe(false);
    expect(isValidImageProfileId('a')).toBe(false);
  });
});

describe('composeImagePrompt', () => {
  it('joins non-empty prefix, prompt, and suffix with commas', () => {
    expect(composeImagePrompt(' cinematic ', 'a cat', ' 4k ')).toBe('cinematic, a cat, 4k');
  });

  it('omits empty segments', () => {
    expect(composeImagePrompt('', 'solo', '')).toBe('solo');
    expect(composeImagePrompt('  ', '  ', '  ')).toBe('');
  });
});

describe('parseImageSeed', () => {
  it('parses integer seeds and rejects blanks or non-integers', () => {
    expect(parseImageSeed('42')).toBe(42);
    expect(parseImageSeed('  ')).toBeNull();
    expect(parseImageSeed('abc')).toBeNull();
    expect(parseImageSeed('3.14')).toBe(3);
  });
});

describe('estimateImageCostUsd', () => {
  it('sums per-image and per-step costs', () => {
    expect(estimateImageCostUsd({ per_image: 0.01, per_step: 0.002 }, 4)).toBeCloseTo(0.018);
  });

  it('returns null when model is missing or has no pricing fields', () => {
    expect(estimateImageCostUsd(null, 4)).toBeNull();
    expect(estimateImageCostUsd({ per_image: null, per_step: null }, 4)).toBeNull();
  });

  it('treats null pricing components as zero', () => {
    expect(estimateImageCostUsd({ per_image: 0.05, per_step: null }, 10)).toBe(0.05);
  });
});
