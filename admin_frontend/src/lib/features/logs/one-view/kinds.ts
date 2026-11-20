/**
 * The five story kinds (Logging and tracing plan, decision of Fri, Nov 20, 2026): one fixed list in the logging
 * foundation. The kind decides how a story is drawn; its name (declared by its feature) says what it is.
 */
import type { StoryKind } from '$lib/api/logs';

/** A timed step, placed in its story: from the story's first line, and how deep under its parent. */
export type StoryStep = { step: string; source: string; start_ms: number; elapsed_ms: number; outcome: string; depth: number };

export const STORY_KINDS: readonly { kind: StoryKind; label: string; says: string }[] = [
  { kind: 'conversation', label: 'Conversation', says: 'A message in, the thinking, the reply out' },
  { kind: 'event', label: 'Event', says: 'Something outside happened, and what it set off' },
  { kind: 'round', label: 'Round', says: "A timer's work, what it changed and what it set off" },
  { kind: 'action', label: 'Action', says: 'A person did something on a page, and its outcome' },
  { kind: 'job', label: 'Job', says: 'Long work in stages, with progress' }
];

export const kindLabel = (kind: StoryKind) => STORY_KINDS.find((k) => k.kind === kind)?.label ?? kind;
