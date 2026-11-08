/** Breaks the apiRequest ↔ admin-session import cycle: the client signals a 401, the session reacts. */

type SignedOutHandler = () => void;

let handler: SignedOutHandler | null = null;

export function registerSignedOutHandler(next: SignedOutHandler): void {
  handler = next;
}

/** The server said "sign in first" (HTTP 401): the session ended or was never there. */
export function signalSignedOut(): void {
  handler?.();
}
