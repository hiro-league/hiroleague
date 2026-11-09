<script lang="ts">
  // Logs → AI usage (Phase 7b): the days shown, picked on a calendar — a first and a last day
  // (up to today), or one day alone — with ‹ › stepping the same number of days back or forward.
  // Ported from HomeHiro's LLM usage day-range picker.
  import { CalendarDate, type DateValue } from '@internationalized/date';
  import type { DateRange } from 'bits-ui';
  import { CalendarDays, ChevronLeft, ChevronRight } from '@lucide/svelte';
  import * as Popover from '$lib/components/ui/popover';
  import { RangeCalendar } from '$lib/components/ui/range-calendar/index.js';
  import { dayLabel, spanLabel, type Span } from './ai-usage';

  let {
    span,
    now,
    canLater,
    onpick,
    onshift
  }: { span: Span; now: number; canLater: boolean; onpick: (s: Span) => void; onshift: (dir: -1 | 1) => void } = $props();

  const toDate = (t: number) => {
    const d = new Date(t);
    return new CalendarDate(d.getFullYear(), d.getMonth() + 1, d.getDate());
  };
  const toTime = (d: DateValue, days = 0) => new Date(d.year, d.month - 1, d.day + days).getTime();

  let open = $state(false);
  let value = $state<DateRange>({ start: undefined, end: undefined });
  let placeholder = $state<DateValue | undefined>(undefined);
  let fresh = false; // nothing clicked since it opened: the days shown are only highlighted
  const today = $derived(toDate(now));

  function opened(o: boolean) {
    open = o;
    if (!o) return;
    value = { start: toDate(span.from), end: toDate(span.to - 1) };
    placeholder = toDate(span.to - 1).subtract({ months: 1 });
    fresh = true;
  }
  function picked(v: DateRange) {
    if (fresh) {
      // The first click starts new days, whatever the calendar makes of it with the days highlighted.
      fresh = false;
      const moved = (a?: DateValue, b?: DateValue) => !!a && (!b || a.compare(b) !== 0);
      const clicked = moved(v.start, value.start) ? v.start : moved(v.end, value.end) ? v.end : (v.start ?? value.start);
      value = { start: clicked, end: undefined };
      return;
    }
    value = v;
    if (v.start && v.end) pick(v.start, v.end);
  }
  function pick(first: DateValue, last: DateValue) {
    onpick({ from: toTime(first), to: toTime(last, 1) });
    open = false;
  }
  const btn = 'inline-flex h-8 items-center justify-center rounded-md border bg-background text-muted-foreground hover:bg-accent disabled:opacity-30';
</script>

<span class="inline-flex items-center gap-1">
  <button type="button" class="{btn} w-8" onclick={() => onshift(-1)} title="The same number of days before" aria-label="Days before"
    ><ChevronLeft size={16} /></button
  >
  <Popover.Root bind:open={() => open, opened}>
    <Popover.Trigger
      class="inline-flex h-8 min-w-44 items-center gap-2 rounded-md border bg-background px-2.5 font-sans text-sm font-medium hover:bg-accent"
      title="Pick days on a calendar"
    >
      <CalendarDays size={14} class="text-muted-foreground" />{spanLabel(span, now)}
    </Popover.Trigger>
    <Popover.Content class="w-auto p-0" align="start">
      <RangeCalendar bind:value={() => value, picked} bind:placeholder numberOfMonths={2} maxValue={today} weekStartsOn={1} />
      <div class="flex items-center gap-2 border-t px-3 py-2 font-sans text-xs text-muted-foreground">
        {#if value.start && !value.end}
          <span>Now pick the last day, or</span>
          <button
            type="button"
            class="rounded-md border px-2 py-1 text-foreground hover:bg-accent"
            onclick={() => value.start && pick(value.start, value.start)}>Only {dayLabel(toTime(value.start), now)}</button
          >
        {:else}
          <span>Pick the first day, then the last. One day shows its hours.</span>
        {/if}
      </div>
    </Popover.Content>
  </Popover.Root>
  <button type="button" class="{btn} w-8" disabled={!canLater} onclick={() => onshift(1)} title="The same number of days after" aria-label="Days after"
    ><ChevronRight size={16} /></button
  >
</span>
