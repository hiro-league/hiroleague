// The icons an app may name for its tile (its site's `icon`, the backend kit's `Extension.site_icon`): a few of
// lucide's names, so the kit doesn't carry every icon. A name not here draws a plain app window; add one here when an
// app names a new one. "hiroleague" isn't here: the core's tile shows the core's own logo (app-switcher.svelte).
import { AppWindow, ChartColumn, GraduationCap, House, Network, ScanFace } from '@lucide/svelte';

export const APP_ICONS = {
	house: House, // HomeHiro
	network: Network, // NetHiro
	'scan-face': ScanFace, // TrainHiro
	'graduation-cap': GraduationCap, // StudyHiro
	chart: ChartColumn // the code reports
} as const;

export const appIcon = (name: string) => APP_ICONS[name as keyof typeof APP_ICONS] ?? AppWindow;

/** Where the core's logo is, on the core's own address (the admin serves it there). */
export const coreLogo = (url: string) => `${url.replace(/\/$/, '')}/images/logo-only2.png`;
