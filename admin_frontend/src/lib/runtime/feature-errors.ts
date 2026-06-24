import { serverReadiness } from './server-readiness.svelte';

/** Inline/toast errors defer to the shell banner while the server is unreachable. */
export function featureErrorFrom(err: unknown, fallback = 'Request failed.'): string | null {
  if (!serverReadiness.ready) return null;
  if (err instanceof Error) return err.message;
  return fallback;
}
