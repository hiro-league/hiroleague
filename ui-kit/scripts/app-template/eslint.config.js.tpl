// Lint (npm run lint, also part of npm run check): the setup every Hiro frontend shares, from the UI kit
// (.kit/lib/eslint-preset.js: type-aware rules, the house rules). Rules that are this app's own go after it.
import { defineConfig } from 'eslint/config';
import { hiroEslint } from './.kit/lib/eslint-preset.js';

export default defineConfig(...hiroEslint({ dirname: import.meta.dirname }));
