// The Logs page's state: the lines of the span, view and source picked (loaded again when the web app
// writes a line; the 30 s re-read went with the WhatsApp worker's files), and what the page makes of them:
// the area, the search, repeats grouped.
import { getLogs, type LogLine, type Source, type Span, type View } from './api';
import { Resource } from '$kit/state/resource.svelte';
import { areaOf, group, isError, isProblem, single, type Group } from './lines';

export class LogsPage {
	view = $state<View>('problems');
	span = $state<Span>('24h');
	source = $state<Source | 'all'>('all');
	area = $state('all');
	search = $state('');
	grouped = $state(true);
	open = $state<Set<string>>(new Set());

	readonly loaded = new Resource((signal) => getLogs(this.span, this.view, this.source, signal), { on: ['logs', 'hello'] });
	readonly lines: LogLine[] = $derived(this.loaded.data?.lines ?? []);
	/** When the times were worked out ("5 min ago"), so every row says the same. */
	readonly now = $derived.by(() => (void this.loaded.data, Date.now()));

	readonly errors = $derived(this.lines.filter((l) => isError(l.level)).length);
	readonly warnings = $derived(this.lines.filter((l) => l.level === 'WARNING').length);

	/** What went wrong most often in the span. */
	readonly top = $derived(
		group(this.lines.filter((l) => isProblem(l.level)))
			.sort((a, b) => b.count - a.count || b.last.localeCompare(a.last))
			.slice(0, 3)
	);

	readonly areas = $derived([...new Set(this.lines.map((l) => areaOf(l.logger)))].sort());

	readonly shown = $derived.by(() => {
		const q = this.search.trim().toLowerCase();
		const lines = this.lines.filter(
			(l) =>
				(this.area === 'all' || areaOf(l.logger) === this.area) &&
				(!q || `${l.message}\n${l.detail ?? ''}\n${l.logger}`.toLowerCase().includes(q))
		);
		return this.grouped ? group(lines) : single(lines);
	});

	toggle(key: string) {
		const next = new Set(this.open);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		this.open = next;
	}

	/** From "Most often": show only that kind of line. */
	focus(g: Group) {
		this.area = areaOf(g.line.logger);
		this.search = g.line.message.replace(/\d+(\.\d+)?.*$/, '').trim().slice(0, 40);
		this.open = new Set([g.key]);
	}

	clear() {
		this.area = 'all';
		this.search = '';
		this.source = 'all';
	}
}
