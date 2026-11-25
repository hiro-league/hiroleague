// Settings → HiroLeague: what waits for the owner's approval in HiroLeague, as a line people read (Permissions phase 8).
// Pure, with tests (approval.test.ts).
import type { WaitingItem } from './api';

/** "Ask another app for its data (net)." from the core's words and the item's subject. */
export function waitingLine(w: WaitingItem): string {
	const words = w.words.charAt(0).toUpperCase() + w.words.slice(1);
	return `${words}${w.subject ? ` (${w.subject})` : ''}.`;
}
