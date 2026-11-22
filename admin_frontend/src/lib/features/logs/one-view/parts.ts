/**
 * The parts that log, as people name them: the core's own streams (server, gateway, CLI, a channel), each app's
 * stream in the core's log store (`app-<its name>`) and the phone's (`device`). A page's problems are lines of its
 * app's stream with the area `<app>.page`.
 */

const APPS: Record<string, string> = {
  home: 'HomeHiro',
  net: 'NetHiro',
  train: 'TrainHiro',
  eval: 'EvalHiro',
  study: 'StudyHiro',
  reports: 'CodeHiro'
};

export type PartKind = 'server' | 'gateway' | 'cli' | 'channel' | 'app' | 'device';

export function partKind(source: string): PartKind {
  if (source === 'server' || source === 'gateway' || source === 'cli' || source === 'device') return source;
  if (source.startsWith('channel-')) return 'channel';
  return 'app';
}

/** "Core server", "Gateway", "Channel · whatsapp", "HomeHiro", "Phone". */
export function partLabel(source: string): string {
  switch (partKind(source)) {
    case 'server':
      return 'Core server';
    case 'gateway':
      return 'Gateway';
    case 'cli':
      return 'CLI';
    case 'device':
      return 'Phone';
    case 'channel':
      return `Channel · ${source.slice('channel-'.length)}`;
    case 'app': {
      const name = source.replace(/^app-/, '');
      return APPS[name] ?? name;
    }
  }
}

/** Whether a part is the core itself (server, gateway, CLI, a channel). */
export const isCore = (source: string) => !['app', 'device'].includes(partKind(source));

/** A browser page's problem: its app logs it under `<app>.page`. */
export const isPageArea = (area: string) => area.endsWith('.page');
