/** Grace period before a disconnected SSE stream is treated as degraded. */
export const DEGRADE_GRACE_MS = 8000;

export type DegradedDetector = {
  readonly degraded: boolean;
  onConnected(): void;
  onDisconnected(): void;
  onReset(): void;
};

/**
 * Flips `degraded` after `graceMs` of continuous disconnect; clears on reconnect.
 * Shared by the status SSE singleton and the knowledge events multiplexer.
 */
export function createDegradedDetector(graceMs: number = DEGRADE_GRACE_MS): DegradedDetector {
  let degraded = $state(false);
  let connected = $state(false);
  let degradeTimer: ReturnType<typeof setTimeout> | null = null;

  function clearDegradeTimer(): void {
    if (degradeTimer) {
      clearTimeout(degradeTimer);
      degradeTimer = null;
    }
  }

  function onConnected(): void {
    connected = true;
    degraded = false;
    clearDegradeTimer();
  }

  function onDisconnected(): void {
    connected = false;
    if (!degradeTimer) {
      degradeTimer = setTimeout(() => {
        degradeTimer = null;
        if (!connected) degraded = true;
      }, graceMs);
    }
  }

  function onReset(): void {
    connected = false;
    clearDegradeTimer();
    degraded = false;
  }

  return {
    get degraded() {
      return degraded;
    },
    onConnected,
    onDisconnected,
    onReset
  };
}
