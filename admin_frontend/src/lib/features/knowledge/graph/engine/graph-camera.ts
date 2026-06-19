import type ForceGraph from 'force-graph';
import { FIT_ANIM_MS } from './graph-config';
import type { FgLink, FgNode } from './graph-types';
import type { SearchState } from './graph-engine-types';

type FgInstance = ForceGraph<FgNode, FgLink>;

export class GraphCamera {
  private userMovedCamera = false;
  private programmaticZoom = true;
  private programmaticZoomTimer: ReturnType<typeof setTimeout> | null = null;
  fitPending = false;

  constructor(
    private getFg: () => FgInstance | null,
    private getSearch: () => SearchState
  ) {}

  onUserZoom(): void {
    if (!this.programmaticZoom) this.userMovedCamera = true;
  }

  markIntentionalReframe(): void {
    this.userMovedCamera = false;
  }

  /** Run a programmatic camera fit while suppressing user-move detection. */
  programmaticFit(run: () => void): void {
    this.programmaticZoom = true;
    if (this.programmaticZoomTimer) clearTimeout(this.programmaticZoomTimer);
    run();
    this.programmaticZoomTimer = setTimeout(() => {
      this.programmaticZoom = false;
      this.programmaticZoomTimer = null;
    }, FIT_ANIM_MS + 150);
  }

  fitToView(): void {
    const fg = this.getFg();
    if (!fg) return;
    this.userMovedCamera = false;
    const focus = this.getSearch().focusNodeIds;
    if (focus && focus.size > 0) {
      this.programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 80, (n: FgNode) => focus.has(n.id)));
    } else {
      this.programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 60));
    }
  }

  centerOn(nodeIds: string[], fgNodeById: Map<string, FgNode>): void {
    const fg = this.getFg();
    if (!fg) return;
    const pts = nodeIds
      .map((id) => fgNodeById.get(id))
      .filter((n): n is FgNode => !!n && n.x != null && n.y != null);
    if (pts.length === 0) return;
    const cx = pts.reduce((s, n) => s + (n.x ?? 0), 0) / pts.length;
    const cy = pts.reduce((s, n) => s + (n.y ?? 0), 0) / pts.length;
    this.userMovedCamera = false;
    this.programmaticFit(() => fg.centerAt?.(cx, cy, FIT_ANIM_MS));
  }

  /** Frame search subset after search resolves (setSearch path). */
  maybeFrameSearchFocus(): void {
    const fg = this.getFg();
    if (!fg) return;
    const state = this.getSearch();
    const focus = state.focusNodeIds;
    if (!focus || focus.size === 0 || this.userMovedCamera) return;
    if (this.fitPending) return;
    this.programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 80, (n: FgNode) => focus.has(n.id)));
  }

  /** On sim settle, reframe ONLY the active-search matched subset. */
  onEngineStop(): void {
    const fg = this.getFg();
    if (!fg || !this.fitPending) return;
    this.fitPending = false;
    if (this.userMovedCamera) return;
    const state = this.getSearch();
    if (state.searchActive) {
      const focus = state.focusNodeIds;
      if (focus && focus.size > 0) {
        this.programmaticFit(() => fg.zoomToFit?.(FIT_ANIM_MS, 60, (n: FgNode) => focus.has(n.id)));
      }
    }
  }

  destroy(): void {
    if (this.programmaticZoomTimer) clearTimeout(this.programmaticZoomTimer);
    this.programmaticZoomTimer = null;
  }
}
