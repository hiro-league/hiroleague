// d3-force-3d ships no type declarations and has no `@types` package. force-graph already depends
// on it internally; we import `forceCollide` directly to reuse its quadtree (O(n log n)) collision —
// it replaced a hand-rolled O(n²) collide that could not scale past a small dev graph (the real
// target is tens of thousands of nodes). Minimal surface: only what graph-canvas-engine.ts uses.
declare module 'd3-force-3d' {
  export interface ForceCollide<N> {
    (alpha: number): void;
    initialize?(nodes: N[], ...args: unknown[]): void;
    radius(): (node: N, i: number, nodes: N[]) => number;
    radius(radius: number | ((node: N, i: number, nodes: N[]) => number)): this;
    strength(): number;
    strength(strength: number): this;
    iterations(): number;
    iterations(iterations: number): this;
  }
  export function forceCollide<N = unknown>(
    radius?: number | ((node: N, i: number, nodes: N[]) => number)
  ): ForceCollide<N>;
}
