import { defineConfig } from 'vitest/config';
import { hiroVite } from './src/lib/vite-preset.js';

// The kit's own project: its gallery (src/routes) and its checks and tests. The apps do not build this; they read
// src/lib as source (README.md). The settings are the apps' too (src/lib/vite-preset.js); only the aliases differ:
// the kit's files import each other at $kit, and read the app at $hiro-app, which here is the sample one (src/sample).
export default defineConfig({ ...hiroVite({ kit: 'src/lib', app: 'src/sample' }) });
