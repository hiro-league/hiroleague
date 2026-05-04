# Resource Sync — plan overview

> Lightweight cover sheet for the execution plan at
> `.cursor/plans/resource_sync_protocol_2bf4d8a1.plan.md`.
> For the **architecture and concepts**, read `docs/resource-sync.md` first.

## Where to read what

| If you want to… | Read… |
|---|---|
| Understand what Resource Sync is, why it exists, the wire protocol, the reliability model, the diagrams. | [`docs/resource-sync.md`](./resource-sync.md) |
| Know the exact files/steps to land it, with acceptance criteria and breaking-change notes. | [`.cursor/plans/resource_sync_protocol_2bf4d8a1.plan.md`](../.cursor/plans/resource_sync_protocol_2bf4d8a1.plan.md) |
| Re-orient mid-implementation when a step feels weird. | Section 7 (worked example) of `docs/resource-sync.md`. |
| Add a new feature later without re-reading everything. | Section 9 (conventions and rules) of `docs/resource-sync.md`. |

## Plan size, honestly

The plan is currently scoped end-to-end (all 14 steps, all three tiers). That
is intentionally not trimmed — it documents the full target shape.

If you want to ship in smaller pieces, the suggested split is:

- **Tier 1 (minimal modular substrate)** — Steps 1, 3 (without versioning),
  6, 8, 9.
- **Tier 2 (reliability)** — Steps 2, 5, 7, 11, 12.
- **Tier 3 (cleanups + renames)** — Steps 4, 10, 13, 14.

See section 8 of `docs/resource-sync.md` for what each tier delivers.

## Working on the plan

When executing a step:

1. Re-read the matching part of `docs/resource-sync.md` (it has the rationale
   the plan deliberately omits).
2. Follow the plan's file-level instructions verbatim.
3. After landing the step, tick its acceptance criterion in the plan.
4. If you discover a divergence between concept and plan, fix the concept doc
   first — it's the source of truth.

