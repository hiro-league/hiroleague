// mockup: the owner's approval of each app, kept in this browser tab only (Permissions phase 8). One store, read by
// the Extensions page and the top bar's mark, until the core serves what each app is approved for.
import { MOCK_APPROVALS, waitingAsks, waits, type Approval } from './approval-mockup';

function copy(): Record<string, Approval> {
  return Object.fromEntries(
    Object.entries(MOCK_APPROVALS).map(([name, a]) => [name, { ...a, identity: { ...a.identity }, asks: a.asks.map((x) => ({ ...x })) }])
  );
}

let approvals = $state<Record<string, Approval>>(copy());
/** Apps the owner declined: gone from the list, as a declined app is not paired. */
let declined = $state<string[]>([]);

export const approvalMockup = {
  of: (name: string): Approval | null => (declined.includes(name) ? null : (approvals[name] ?? null)),
  isDeclined: (name: string) => declined.includes(name),
  /** The app waits for the owner: never answered, or a new version asks for more. */
  waits(name: string): boolean {
    const a = declined.includes(name) ? null : approvals[name];
    return a ? waits(a) : false;
  },
  /** How many of its asks wait for the owner. */
  askedCount(name: string): number {
    const a = declined.includes(name) ? null : approvals[name];
    return a ? waitingAsks(a).length : 0;
  },
  /** Declining takes the app away: a new app, or a new version's required ask. An optional new ask is only left off. */
  declinable(name: string): boolean {
    const a = declined.includes(name) ? null : approvals[name];
    return !!a && (a.pending || a.asks.some((x) => x.waiting && x.required));
  },
  /** Never answered: paired, but it gets nothing it asks for, so it isn't working yet. */
  pending: (name: string): boolean => !declined.includes(name) && !!approvals[name]?.pending,
  /** How many apps wait for the owner's answer. */
  get waitingCount() {
    return Object.entries(approvals).filter(([name, a]) => !declined.includes(name) && waits(a)).length;
  },
  /** An optional ask's switch, before Approve. */
  setSwitch(name: string, index: number, on: boolean) {
    const ask = approvals[name]?.asks[index];
    if (ask && !ask.required) ask.approved = on;
  },
  /** Approve: every required ask, the optional ones as switched; nothing waits any more. */
  approve(name: string) {
    const a = approvals[name];
    if (!a) return;
    for (const ask of a.asks) {
      if (ask.required) ask.approved = true;
      ask.waiting = false;
    }
    a.pending = false;
  },
  /** Decline: a new app is not paired; a new version's required ask declined removes the app too. */
  decline(name: string) {
    declined = [...declined, name];
  },
  /** Back to the mock data, for trying the mockup again. */
  reset() {
    approvals = copy();
    declined = [];
  }
};
