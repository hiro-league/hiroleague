/**
 * The Stories tab's list and filters (Logging and tracing plan, phase 6b), shared by its toolbar (in the page header's
 * row under the title) and its list: the named stories of the time window, from the core's log tools
 * (`/logs/stories`), narrowed here by kind, source, problems and search.
 */
import { errorMessage } from '$kit/api/client';
import { getLogStories, logWindowSpan, type LogStories, type LogTimeRange } from '$lib/api/logs';

export class StoriesFilters {
  search = $state('');
  kinds = $state<string[]>([]);
  sources = $state<string[]>([]);
  withProblems = $state(false);
  window = $state<'last' | LogTimeRange>('1h');

  data = $state<LogStories | null>(null);
  loading = $state(false);
  error = $state<string | null>(null);

  /** The parts the window's stories went through, for the Source filter. */
  parts = $derived([...new Set((this.data?.stories ?? []).flatMap((s) => s.sources))].sort());

  rows = $derived(
    (this.data?.stories ?? []).filter(
      (s) =>
        (this.kinds.length === 0 || this.kinds.includes(s.kind)) &&
        (this.sources.length === 0 || s.sources.some((p) => this.sources.includes(p))) &&
        (!this.withProblems || s.problems > 0) &&
        (!this.search.trim() || `${s.label} ${s.title}`.toLowerCase().includes(this.search.trim().toLowerCase()))
    )
  );

  async load(): Promise<void> {
    const asked = this.window;
    this.loading = true;
    this.error = null;
    try {
      const got = await getLogStories({ since: logWindowSpan(asked === 'last', asked === 'last' ? '1d' : asked) });
      if (asked === this.window) this.data = got;
    } catch (e) {
      this.error = errorMessage(e);
    } finally {
      this.loading = false;
    }
  }
}
