import { LOG_LEVELS, type LogLevel } from '$lib/api/logs';
import { cn } from '$lib/utils';

/** Shared compact pill layout for log source + level filter chips (matches table tone helpers). */
export const LOGS_FILTER_CHIP_LAYOUT =
  'h-6 min-h-6 shrink-0 rounded-full border px-2.5 py-0 text-[0.62rem] font-semibold leading-none gap-1';

/** Per-level hue (no weight) — use for icons where label stays regular body text. */
const LEVEL_COLOR: Record<LogLevel, string> = {
  DEBUG: 'text-sky-400',
  FINEINFO: 'text-cyan-400',
  INFO: 'text-emerald-500',
  WARNING: 'text-amber-500',
  ERROR: 'text-red-500',
  CRITICAL: 'text-fuchsia-500'
};

/** Tailwind class sets for log level text (filter chips + detail panel; severe levels stay bold). */
const LEVEL_TEXT: Record<LogLevel, string> = {
  DEBUG: LEVEL_COLOR.DEBUG,
  FINEINFO: LEVEL_COLOR.FINEINFO,
  INFO: LEVEL_COLOR.INFO,
  WARNING: cn(LEVEL_COLOR.WARNING, 'font-bold'),
  ERROR: cn(LEVEL_COLOR.ERROR, 'font-bold'),
  CRITICAL: cn(LEVEL_COLOR.CRITICAL, 'font-bold')
};

const MODULE_BUCKET_TEXT = [
  'text-sky-400',
  'text-fuchsia-500',
  'text-amber-500',
  'text-emerald-500'
] as const;

function isLogLevel(value: string): value is LogLevel {
  return LOG_LEVELS.includes(value as LogLevel);
}

export function logLevelTextClass(level: string): string {
  return isLogLevel(level) ? LEVEL_TEXT[level] : '';
}

/** Level hue for icons (table Lvl column: icon only, no bold). */
export function logLevelAccentClass(level: string): string {
  return isLogLevel(level) ? LEVEL_COLOR[level] : '';
}

export function logModuleTextClass(moduleName: string): string {
  const bucket =
    Array.from(moduleName).reduce((total, character) => total + (character.codePointAt(0) ?? 0), 0) %
    MODULE_BUCKET_TEXT.length;
  return MODULE_BUCKET_TEXT[bucket] ?? MODULE_BUCKET_TEXT[0];
}

export function logSourceFilterChipClass(active: boolean): string {
  return cn(
    LOGS_FILTER_CHIP_LAYOUT,
    active ? 'border-border' : 'border-transparent text-muted-foreground'
  );
}

export function logLevelFilterChipClass(active: boolean, level: LogLevel): string {
  return cn(
    LOGS_FILTER_CHIP_LAYOUT,
    active
      ? cn('border-border', logLevelTextClass(level))
      : 'border-transparent text-muted-foreground'
  );
}
