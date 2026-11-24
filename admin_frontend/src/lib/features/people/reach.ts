/**
 * Permissions, phase 1: how far a right reaches. A right about people's things (declared `personal`) is granted for a
 * person's own things or for everyone's; any other right is simply granted or not.
 *
 * Grant keys: `<feature>.<right>` reaches everyone's (and is the only key a non-personal right has);
 * `<feature>.<right>:own` reaches the person's own. Granting any right of a feature that has `see` grants its `see`,
 * with at least the same reach.
 */

export type Reach = 'no' | 'own' | 'all';

export const SEE = 'see';
export const OWN_SUFFIX = ':own';

const RANK: Record<Reach, number> = { no: 0, own: 1, all: 2 };

/** The reach a role's keys give one right. */
export function reachOf(keys: ReadonlySet<string>, key: string): Reach {
  if (keys.has(key)) return 'all';
  if (keys.has(key + OWN_SUFFIX)) return 'own';
  return 'no';
}

/** A feature's right as the reach rules need it: a right that isn't `personal` is everyone's or nothing. */
export type ReachRight = { id: string; personal: boolean };

/**
 * A feature's reaches after one right is set; `reaches` is what each right has now. As the core keeps them
 * (hiro_channel_sdk.access.normalize):
 * - raising a right raises `see` to at least the same reach, and to everyone's when `see` isn't personal;
 * - lowering `see` lowers every other right to at most its reach, and drops a right that isn't personal when `see`
 *   becomes their own (such a right has no "their own").
 */
export function setReach(
  rights: readonly ReachRight[],
  reaches: Readonly<Record<string, Reach>>,
  right: string,
  reach: Reach
): Record<string, Reach> {
  const personal = new Map(rights.map((r) => [r.id, r.personal]));
  const cap = (id: string, to: Reach): Reach => (to === 'own' && !personal.get(id) ? 'no' : to);
  const next: Record<string, Reach> = {};
  for (const r of rights) next[r.id] = reaches[r.id] ?? 'no';
  next[right] = personal.get(right) || reach === 'no' ? reach : 'all';
  if (!personal.has(SEE)) return next;
  if (right === SEE) {
    for (const r of rights) if (RANK[next[r.id]] > RANK[next[SEE]]) next[r.id] = cap(r.id, next[SEE]);
  } else if (next[right] !== 'no') {
    const wanted: Reach = personal.get(SEE) ? next[right] : 'all';
    if (RANK[next[SEE]] < RANK[wanted]) next[SEE] = wanted;
  }
  return next;
}

/**
 * What a role has in one feature, in a few words for the overview table: "—", "Everything", "Everything, their own",
 * or the rights' names, each own one marked.
 */
export function featureSummary(rights: readonly { id: string; name: string }[], reaches: Readonly<Record<string, Reach>>): string {
  const have = rights.filter((r) => (reaches[r.id] ?? 'no') !== 'no');
  if (have.length === 0) return '—';
  const own = have.filter((r) => reaches[r.id] === 'own');
  if (have.length === rights.length && rights.length > 1) {
    if (own.length === 0) return 'Everything';
    if (own.length === have.length) return 'Everything, their own';
  }
  return have.map((r) => (reaches[r.id] === 'own' ? `${r.name} (their own)` : r.name)).join(', ');
}

/**
 * A role's keys in one source with one feature's rights set to these reaches: that feature's keys (plain and `:own`)
 * are replaced, every other key stays. The core checks and orders what it is sent.
 */
export function withReaches(
  keys: Iterable<string>,
  feature: string,
  reaches: Readonly<Record<string, Reach>>
): string[] {
  const kept = [...keys].filter((k) => !k.startsWith(`${feature}.`));
  for (const [right, reach] of Object.entries(reaches)) {
    if (reach === 'all') kept.push(`${feature}.${right}`);
    else if (reach === 'own') kept.push(`${feature}.${right}${OWN_SUFFIX}`);
  }
  return kept;
}

/** A person's roles in the roles' order (Owner first): the first of them is the one `role_id` keeps. */
export function inRoleOrder(roleIds: readonly string[], order: readonly string[]): string[] {
  const at = (id: string) => {
    const i = order.indexOf(id);
    return i === -1 ? order.length : i;
  };
  return [...new Set(roleIds)].sort((a, b) => at(a) - at(b));
}
