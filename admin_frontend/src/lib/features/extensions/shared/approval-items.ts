// What an app's Permissions tab shows (Permissions phase 8): the items the core says it asks, grouped. A new
// version's extras come first ("New in this version"); then Required and Optional. The app's address and network
// name are on the Info tab, so they show here only when a new one waits for the owner's yes.
import type { AppApproval, ApprovalItem } from '$lib/api/extensions';

/** The item as the approve route takes it: "permission" or "permission:subject". */
export const itemKey = (i: ApprovalItem): string => (i.subject ? `${i.permission}:${i.subject}` : i.permission);

const IDENTITY = new Set(['site.address', 'site.name']);

export type ApprovalGroups = { fresh: ApprovalItem[]; required: ApprovalItem[]; optional: ApprovalItem[] };

/** The lists the tab shows. A never-answered app has no "new": everything it asks is in Required and Optional. */
export function groups(a: AppApproval): ApprovalGroups {
  const shown = a.items.filter((i) => i.understood && (!IDENTITY.has(i.permission) || (i.waiting && !a.pending)));
  const fresh = a.pending ? [] : shown.filter((i) => i.waiting);
  const rest = shown.filter((i) => !fresh.includes(i) && !IDENTITY.has(i.permission));
  return { fresh, required: rest.filter((i) => i.required), optional: rest.filter((i) => !i.required) };
}

/** The optional items switched on before the owner touches a switch: the ones approved now. */
export const approvedOptional = (a: AppApproval): string[] =>
  a.items.filter((i) => i.understood && !i.required && i.approved).map(itemKey);

/** Declining takes the app away: a never-answered app, or a new version's required ask. */
export const declinable = (a: AppApproval): boolean => a.pending || a.items.some((i) => i.waiting && i.required);

/** The network name it holds, "name → port", for the Info tab ("" when none). */
export function networkName(a: AppApproval | null): string {
  const held = a?.items.find((i) => i.permission === 'site.name' && i.approved);
  if (!held) return '';
  const at = held.subject.lastIndexOf(':');
  return at > 0 ? `${held.subject.slice(0, at)} → port ${held.subject.slice(at + 1)}` : held.subject;
}
