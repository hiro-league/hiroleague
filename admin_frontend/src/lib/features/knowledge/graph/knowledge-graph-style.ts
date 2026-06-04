/**
 * Shared node-type visual vocabulary for the knowledge graph view.
 *
 * Lives outside the panel/filter-bar so the canvas renderer and the filter
 * strip agree on colours. Node types are DERIVED FROM DATA (Graphiti can emit
 * arbitrary entity types), so this map is just the "known" palette — anything
 * Graphiti returns that isn't listed falls back to the Entity slate via
 * `colorFor`. The Lucide canvas icons stay in KnowledgeGraphPanel because they
 * are canvas-specific (Path2D), not needed by the DOM filter chips.
 */

// Colour per known ontology type (Person/Place/Event/Org/Object + Entity fallback).
export const TYPE_COLORS: Record<string, string> = {
  Person: '#60a5fa',
  Place: '#34d399',
  Event: '#fbbf24',
  Organization: '#f472b6',
  Object: '#a78bfa',
  Entity: '#94a3b8'
};

export const colorFor = (type: string): string => TYPE_COLORS[type] ?? TYPE_COLORS.Entity;

// Preferred ordering for the known types in the filter strip; any unknown
// (Graphiti-emitted) type sorts after these, alphabetically.
export const KNOWN_NODE_TYPE_ORDER: readonly string[] = [
  'Person',
  'Place',
  'Organization',
  'Event',
  'Object',
  'Entity'
];
