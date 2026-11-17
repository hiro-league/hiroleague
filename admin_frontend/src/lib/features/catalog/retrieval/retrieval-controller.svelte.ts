/**
 * Catalog → Profiles: embedding and reranker profiles, and the uses that point at them (preferences `embedding.*` and
 * `rerank.*`, Eval becomes its own app, step 2).
 *
 * - Profiles are kept in preferences (`embedding.profiles`, `rerank.profiles`) and written through the preferences API,
 *   like voice profiles. A reranker profile also holds where a local model runs (`device`).
 * - Hiro's own four searches are preference fields that each pick one profile (`graph.embedder_profile`,
 *   `knowledge.embedder_profile`, `graph.reranker.profile`, `knowledge.retrieval.reranker.profile`); the extensions'
 *   uses are `embedding.uses` / `rerank.uses["<extension>:<use>"]`, declared by each extension (`/api/search/uses`).
 * - An embedder whose data is indexed is locked (`*.embedder_profile_locked`): its pick, and the model of the profile
 *   it picked, can't change (the server refuses it too). The model picker is the settings' own, over the catalog's
 *   embedding or rerank models and the local ones (with their downloads).
 */
import { errorMessage } from '$kit/api/client';
import { toast } from '$kit/ui/toast.svelte';
import { getPreferences, patchPreferences, type WorkspacePreferences } from '$lib/api/preferences';
import { listSearchUses, type SearchUseGroup } from '$lib/api/search';
import { createLocalModelDownloads } from '$lib/features/preferences/state/local-model-downloads.svelte';
import { createModelCatalog } from '$lib/features/preferences/state/model-catalog.svelte';
import { voiceProfileId } from '$lib/features/catalog/voice/voice-controller.svelte';

export type RetrievalKind = 'embedding' | 'reranker';

/** What a profile holds (the preferences shape). */
export type RetrievalFields = { label: string; model: string; device?: string | null };
export type RetrievalProfile = RetrievalFields & { id: string; kind: RetrievalKind };

export type RetrievalUse = {
  key: string;
  /** "Hiro" for the core's own, else the extension's name. */
  source: string;
  kind: RetrievalKind;
  label: string;
  profileId: string | null;
  /** Hiro's: the preference field holding the pick. */
  path?: string;
  /** The pick can't change: the data is indexed with this model. */
  lockedBecause?: string;
  /** A note on the use itself (e.g. when it is switched off in Settings). */
  note?: string;
  /** An extension's use it no longer declares. */
  removed?: boolean;
};

export type RetrievalModel = { id: string; name: string; provider: string; local: boolean; dims?: number };

export const SECTION = { embedding: 'embedding', reranker: 'rerank' } as const;
export const HIRO = 'Hiro';

export class RetrievalController {
  prefs = $state<WorkspacePreferences | null>(null);
  groups = $state<SearchUseGroup[]>([]);
  loading = $state(false);
  error = $state<string | null>(null);
  /** The catalog's models and providers (the settings' own lists), for the model picker and the names. */
  catalog = createModelCatalog(toast.show);
  /** Local models' download status (the settings' own store). */
  downloads = createLocalModelDownloads(toast.show);
  #catalogAsked = false;

  load = async () => {
    this.loading = true;
    if (!this.#catalogAsked) {
      this.#catalogAsked = true;
      void this.catalog.load().catch(() => undefined);
      void this.downloads.load().catch(() => undefined);
    }
    const [prefs, uses] = await Promise.all([
      getPreferences().catch((err) => {
        this.error = errorMessage(err);
        return null;
      }),
      listSearchUses().catch(() => null)
    ]);
    if (prefs) {
      this.prefs = prefs.preferences;
      this.error = null;
    }
    if (uses) this.groups = uses.extensions;
    this.loading = false;
  };

  profiles(kind: RetrievalKind): RetrievalProfile[] {
    const map = (this.prefs?.[SECTION[kind]]?.profiles ?? {}) as Record<string, RetrievalFields>;
    return Object.entries(map)
      .map(([id, p]) => ({ ...p, id, kind }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }

  /** Hiro's four searches first, then each extension's declared uses. */
  get uses(): RetrievalUse[] {
    const p = this.prefs;
    if (!p) return [];
    const hiro: RetrievalUse[] = [
      {
        key: 'hiro:memory_embedding',
        source: HIRO,
        kind: 'embedding',
        label: 'Conversation memory',
        path: 'graph.embedder_profile',
        profileId: p.graph.embedder_profile ?? null,
        lockedBecause: p.graph.embedder_profile_locked
          ? "Hiro's memory graph holds data made with this model: another embedder needs the graph reset."
          : undefined
      },
      {
        key: 'hiro:knowledge_embedding',
        source: HIRO,
        kind: 'embedding',
        label: 'Knowledge base',
        path: 'knowledge.embedder_profile',
        profileId: p.knowledge.embedder_profile ?? null,
        lockedBecause: p.knowledge.embedder_profile_locked
          ? 'The knowledge collection holds documents made with this model: another embedder needs them deleted first.'
          : undefined
      },
      {
        key: 'hiro:memory_rerank',
        source: HIRO,
        kind: 'reranker',
        label: 'Memory fact search',
        path: 'graph.reranker.profile',
        profileId: p.graph.reranker.profile ?? null,
        note:
          p.graph.search_recipe === 'cross_encoder'
            ? undefined
            : 'Asked only when the fact search recipe is Cross-encoder (Settings → Graph engine).'
      },
      {
        key: 'hiro:knowledge_rerank',
        source: HIRO,
        kind: 'reranker',
        label: 'Knowledge retrieval',
        path: 'knowledge.retrieval.reranker.profile',
        profileId: p.knowledge.retrieval.reranker.profile ?? null,
        note: p.knowledge.retrieval.reranker.enabled ? undefined : 'Reranking is off in Settings → Knowledge.'
      }
    ];
    const extensions = this.groups.flatMap((g) => [
      ...g.embedding.map((u) => ({ u, kind: 'embedding' as const })),
      ...g.rerank.map((u) => ({ u, kind: 'reranker' as const }))
    ].map(({ u, kind }) => ({
      key: u.key,
      source: g.extension,
      kind,
      label: u.name,
      profileId: u.profile_id,
      removed: u.status === 'removed'
    })));
    return [...hiro, ...extensions];
  }

  /** The extensions with searching uses, by name. */
  get sources(): string[] {
    return this.groups.map((g) => g.extension);
  }

  usesOf(kind: RetrievalKind, id: string): RetrievalUse[] {
    return this.uses.filter((u) => u.kind === kind && u.profileId === id);
  }

  /** "Hiro: Conversation memory, Knowledge base · Eval: Embedding": a profile's uses, grouped by who asks. */
  usedByLine(kind: RetrievalKind, id: string): string {
    const by = new Map<string, string[]>();
    for (const u of this.usesOf(kind, id)) {
      const who = u.source.charAt(0).toUpperCase() + u.source.slice(1);
      by.set(who, [...(by.get(who) ?? []), u.label]);
    }
    return [...by].map(([who, labels]) => `${who}: ${labels.join(', ')}`).join(' · ');
  }

  /** Why the profile's model can't change: a use whose data is indexed picked it. */
  lockOf(kind: RetrievalKind, id: string): string | undefined {
    return this.usesOf(kind, id).find((u) => u.lockedBecause)?.lockedBecause;
  }

  /** A model's name, provider and where it runs, from the catalog's lists (local embedders also give their size). */
  model(kind: RetrievalKind, modelId: string): RetrievalModel | undefined {
    const rows = kind === 'embedding' ? this.catalog.embeddingOptions : this.catalog.rerankPickerOptions;
    const row = rows.find((m) => m.id === modelId);
    if (!row) return undefined;
    const provider = this.catalog.catalogAllProviders.find((x) => x.id === row.provider_id);
    const local = row.source === 'local' || provider?.hosting === 'local';
    const dims =
      kind === 'embedding' ? this.downloads.localEmbedders.find((m) => m.id === modelId)?.dimension : undefined;
    return { id: row.id, name: row.display_name, provider: provider?.display_name ?? row.provider_id, local, dims };
  }

  /** Save a profile (new: `id` null → an id from its name). Resolves with its id; a refused save throws. */
  save = async (kind: RetrievalKind, id: string | null, fields: RetrievalFields): Promise<string> => {
    const taken = new Set(this.profiles(kind).map((p) => p.id));
    const pid = id ?? voiceProfileId(fields.label, taken);
    const payload: RetrievalFields =
      kind === 'reranker' ? { label: fields.label, model: fields.model, device: fields.device || null } : { label: fields.label, model: fields.model };
    await patchPreferences({ [`${SECTION[kind]}.profiles.${pid}`]: payload });
    await this.load();
    return pid;
  };

  /** Delete a profile: the map without it, and every use that pointed at it cleared. A refused delete throws. */
  remove = async (kind: RetrievalKind, id: string): Promise<void> => {
    const section = SECTION[kind];
    const rest = Object.fromEntries(
      this.profiles(kind)
        .filter((p) => p.id !== id)
        .map(({ id: pid, kind: _k, ...fields }) => [pid, fields])
    );
    const uses = Object.fromEntries(
      Object.entries(this.prefs?.[section]?.uses ?? {}).map(([key, pid]) => [key, pid === id ? null : pid])
    );
    const hiro = Object.fromEntries(
      this.uses.filter((u) => u.path && u.kind === kind && u.profileId === id).map((u) => [u.path as string, null])
    );
    await patchPreferences({ ...hiro, [`${section}.uses`]: uses, [`${section}.profiles`]: rest });
    await this.load();
  };

  /** Point a use at a profile (null: none). Resolves with an error message, or null when saved. */
  pick = async (use: RetrievalUse, profileId: string | null): Promise<string | null> => {
    const path = use.path ?? `${SECTION[use.kind]}.uses.${use.key}`;
    try {
      await patchPreferences({ [path]: profileId });
    } catch (err) {
      return errorMessage(err);
    }
    await this.load();
    return null;
  };
}

/** One controller for the page, so the profile tabs and Uses share the same rows. */
export const retrieval = new RetrievalController();
