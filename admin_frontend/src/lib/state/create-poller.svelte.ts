export type Poller = {
  /** Begins polling; returns the disposer — wire via `$effect(() => poller.start())`. */
  start(): () => void;
  stop(): void;
};

export function createPoller(
  fn: () => void | Promise<void>,
  opts: { intervalMs: number; pauseWhenHidden?: boolean; immediate?: boolean }
): Poller {
  let timer: ReturnType<typeof setInterval> | null = null;
  let inFlight = false;

  async function tick() {
    if (inFlight) return;
    if (opts.pauseWhenHidden && typeof document !== 'undefined' && document.hidden) return;
    inFlight = true;
    try {
      await fn();
    } finally {
      inFlight = false;
    }
  }

  function stop() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function start() {
    stop();
    if (opts.immediate) void tick();
    timer = setInterval(() => void tick(), opts.intervalMs);
    return stop;
  }

  return { start, stop };
}
