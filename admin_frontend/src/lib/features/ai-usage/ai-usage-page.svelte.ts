/**
 * Logs → AI usage (Phase 7b): the page's state — the days shown, the bar size, what the bars are
 * grouped by and measure, and a filter per dimension. Loads the core's hourly rows (`/ai/usage`) for
 * the days shown and the same span before (the tiles compare with it).
 */
import { fetchAiUsage } from '$lib/api/ai';
import {
  applyFilters,
  autoStep,
  bars,
  DIMENSIONS,
  groups,
  inRange,
  periodOf,
  previous,
  shiftSpan,
  spanOf,
  stepsFor,
  totals,
  valuesOf,
  type Dimension,
  type Filters,
  type Metric,
  type Period,
  type Span,
  type Step,
  type UsageRow
} from './ai-usage';

export class AiUsagePage {
  now = Date.now();
  all = $state<UsageRow[]>([]);
  loading = $state(false);
  error = $state<string | null>(null);
  /** The [from, to) the rows in `all` cover, so a filter change doesn't load again. */
  private loadedFor = '';

  span = $state<Span>(spanOf('7d', this.now));
  stepPicked = $state<Step | null>(null);
  groupBy = $state<Dimension>('use');
  metric = $state<Metric>('cost');
  filters = $state<Filters>({});

  period = $derived(periodOf(this.span, this.now));
  steps = $derived(stepsFor(this.span));
  step = $derived(this.stepPicked && this.steps.includes(this.stepPicked) ? this.stepPicked : autoStep(this.span));
  range = $derived({ ...this.span, step: this.step });
  canLater = $derived(shiftSpan(this.span, 1, this.now) !== null);

  inSpan = $derived(inRange(this.all, this.range));
  rows = $derived(applyFilters(this.inSpan, this.filters));
  totals = $derived(totals(this.rows));
  before = $derived(totals(applyFilters(inRange(this.all, previous(this.range, this.now)), this.filters)));
  bars = $derived(bars(this.rows, this.range, this.groupBy, this.metric));
  groups = $derived(groups(this.rows, this.groupBy));

  /** Each filter's checklist: the values in the days shown, with the other filters applied (so counts add up). */
  options = $derived(
    Object.fromEntries(
      DIMENSIONS.map(({ value: d }) => {
        const others = { ...this.filters, [d]: [] };
        return [d, valuesOf(applyFilters(this.inSpan, others), d)];
      })
    ) as Record<Dimension, { value: string; count: number }[]>
  );
  activeFilters = $derived(DIMENSIONS.filter(({ value: d }) => (this.filters[d]?.length ?? 0) > 0));

  /** Load the days shown and the span before, when they changed (the panel calls this from an effect). */
  load = async () => {
    const from = previous(this.range, this.now).from;
    const to = this.range.to;
    const key = `${from}-${to}`;
    if (key === this.loadedFor) return;
    this.loadedFor = key;
    this.loading = true;
    const res = await fetchAiUsage(from, to);
    // A later range picked while this one loaded wins.
    if (this.loadedFor !== key) return;
    this.loading = false;
    if (res.ok && res.data) {
      this.all = res.data.rows;
      this.error = null;
    } else {
      this.error = res.error ?? 'AI usage could not be read.';
      this.all = [];
    }
  };

  setPeriod = (p: Period) => this.setSpan(spanOf(p, this.now));
  setSpan = (s: Span) => {
    this.span = s;
    this.stepPicked = null;
  };
  shift = (dir: -1 | 1) => {
    const s = shiftSpan(this.span, dir, this.now);
    if (s) this.span = s;
  };
  setFilter = (d: Dimension, values: string[]) => {
    this.filters = { ...this.filters, [d]: values };
  };
  clearFilters = () => {
    this.filters = {};
  };
  /** A table row picked: keep only it, and group by the next useful dimension. */
  pick = (key: string) => {
    this.setFilter(this.groupBy, [key]);
    const next: Partial<Record<Dimension, Dimension>> = { kind: 'use', source: 'use', use: 'label', person: 'use', label: 'model', profile: 'model', provider: 'model', model: 'use', billing: 'model', result: 'use' };
    this.groupBy = next[this.groupBy] ?? 'model';
  };
}
