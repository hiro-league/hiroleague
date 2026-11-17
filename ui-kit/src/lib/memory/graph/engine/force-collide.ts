// d3-force-3d ships no type declarations and has no `@types` package. force-graph already depends on it
// internally; the engine imports `forceCollide` directly to reuse its quadtree (O(n log n)) collision — it
// replaced a hand-rolled O(n²) collide that could not scale past a small dev graph (the real target is tens of
// thousands of nodes). The package is typed here, in a module every app that imports the engine loads, with
// the minimal surface graph-canvas-engine.ts uses.
// @ts-expect-error -- d3-force-3d has no types; the cast below gives forceCollide its shape
import { forceCollide as untypedForceCollide } from 'd3-force-3d';

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

export const forceCollide = untypedForceCollide as <N = unknown>(
	radius?: number | ((node: N, i: number, nodes: N[]) => number)
) => ForceCollide<N>;
