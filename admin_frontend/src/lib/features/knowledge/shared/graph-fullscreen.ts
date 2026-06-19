export type GraphFullscreenLifecycleOptions = {
  getFullscreen: () => boolean;
  setFullscreen: (value: boolean) => void;
  onResize: () => void;
  onVisibilityVisible: () => void;
};

/** Two frames so a fullscreen layout swap settles before the canvas re-measures. */
function resizeAfterLayout(onResize: () => void): void {
  requestAnimationFrame(() => requestAnimationFrame(onResize));
}

/**
 * Fullscreen toggle + window/document lifecycle hooks for the graph panel.
 * Call `mount()` from onMount and use the returned cleanup on destroy.
 */
export function createGraphFullscreenLifecycle(opts: GraphFullscreenLifecycleOptions): {
  toggleFullscreen: () => void;
  mount: () => () => void;
} {
  function toggleFullscreen(): void {
    opts.setFullscreen(!opts.getFullscreen());
    resizeAfterLayout(opts.onResize);
  }

  function mount(): () => void {
    function onWindowResize(): void {
      opts.onResize();
    }

    function onKeydown(event: KeyboardEvent): void {
      if (event.key !== 'Escape' || !opts.getFullscreen()) return;
      opts.setFullscreen(false);
      resizeAfterLayout(opts.onResize);
    }

    function onVisibilityChange(): void {
      if (document.visibilityState !== 'visible') return;
      opts.onVisibilityVisible();
    }

    window.addEventListener('resize', onWindowResize);
    window.addEventListener('keydown', onKeydown);
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      window.removeEventListener('resize', onWindowResize);
      window.removeEventListener('keydown', onKeydown);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }

  return { toggleFullscreen, mount };
}
