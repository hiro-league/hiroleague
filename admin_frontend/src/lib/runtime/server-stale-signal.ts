/** Breaks the apiRequest ↔ server-readiness import cycle — client signals, store reacts. */

type StaleHandler = () => void;

let handler: StaleHandler | null = null;

export function registerServerStaleHandler(next: StaleHandler): void {
  handler = next;
}

export function signalServerMaybeUnavailable(): void {
  handler?.();
}
