// How the app reads the core's AI profiles and uses (Settings → AI from HiroLeague, and the per-copy picker). Pure,
// tested next to it (core-ai.test.ts). The core decides; these only say it in words.
import type { CoreProfile, CoreUse, Need } from '$hiro-app/api';

const money = (v: number) => `$${v.toFixed(2)}`; // budgets and a day's spending, to the cent

/** The model as a line: "Google · Gemini 3.8 Flash", "Codex · gpt-6.1-sol". */
export const modelLine = (p: CoreProfile) => `${p.provider} · ${p.model}`;

/** The budget, short: the core's own words when it sends them, else "up to $1.00 a day", "30 an hour"; with
 * "2 at once" when more than one may run. */
export function budgetHint(p: CoreProfile): string {
	const atOnce = p.at_once ?? 1;
	const limit =
		p.budget ??
		(p.kind === 'api'
			? p.max_cost_day != null
				? `up to ${money(p.max_cost_day)} a day`
				: 'no daily limit'
			: p.max_per_hour
				? `${p.max_per_hour} an hour`
				: 'no hourly limit');
	return atOnce > 1 ? `${limit}, ${atOnce} at once` : limit;
}

/** What it used so far: "$0.34 of $1.00 today, 41 asks", "3 of 10 this hour"; empty when the core sent nothing. */
export function usageText(p: CoreProfile): string {
	if (p.kind === 'api') {
		if (p.spent_today == null) return '';
		const of = p.max_cost_day != null ? ` of ${money(p.max_cost_day)}` : '';
		const asks = p.asks_today ? `, ${p.asks_today} ask${p.asks_today === 1 ? '' : 's'}` : '';
		return `${money(p.spent_today)}${of} today${asks}`;
	}
	if (p.this_hour == null) return '';
	return p.max_per_hour ? `${p.this_hour} of ${p.max_per_hour} this hour` : `${p.this_hour} this hour`;
}

/** The names along a use's chain, as the core reported it; a profile the list lacks shows as "a missing profile". */
export const chainNames = (use: CoreUse, profiles: readonly CoreProfile[]) =>
	(use.chain ?? []).map((id) => profiles.find((p) => p.id === id)?.name ?? 'a missing profile');

/** The chain in one line: "Camera questions → Camera on Codex → Local vision". */
export const chainLine = (use: CoreUse, profiles: readonly CoreProfile[]) => chainNames(use, profiles).join(' → ');

/** A profile's own fallbacks, from it: the chain the core sent, else itself and at most two more by `fallback_id`,
 * stopping at a loop (the core refuses loops; this only guards the picture). */
export function fallbacksOf(id: string, profiles: readonly CoreProfile[], max = 3): CoreProfile[] {
	const first = profiles.find((p) => p.id === id);
	if (first?.chain?.length) return first.chain.map((c) => profiles.find((p) => p.id === c)).filter((p): p is CoreProfile => !!p);
	const out: CoreProfile[] = [];
	let at = first;
	while (at && out.length < max && !out.includes(at)) {
		out.push(at);
		at = profiles.find((p) => p.id === at?.fallback_id);
	}
	return out;
}

/** What a use sends, as badges: "Pictures", "Up to 60 pictures", "A sound", "JSON". */
export function needLabels(use: CoreUse): { need: Need; label: string }[] {
	return use.needs.map((need) => ({
		need,
		label: need === 'pictures' ? (use.pictures_up_to ? `Up to ${use.pictures_up_to} pictures` : 'Pictures') : need === 'sound' ? 'A sound' : 'JSON'
	}));
}
