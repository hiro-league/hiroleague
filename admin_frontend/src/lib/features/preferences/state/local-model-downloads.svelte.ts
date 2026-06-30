/**
 * Local model (embedder + reranker) download lifecycle — split out of the preferences controller
 * (Tier-2.2). Owns the live download-status rows and the poll/download/cancel/resume machinery for
 * both kinds; the controller composes this and re-exposes it. Self-contained: the only outside
 * dependency is the toast `notify`.
 *
 * The `localEmbedders` / `localRerankers` rows here are the DOWNLOAD-STATUS rows (percent/status used
 * by the inline download affordance), distinct from the catalog "local model" picker options the
 * controller loads separately.
 */
import {
  cancelKnowledgeEmbedder,
  cancelKnowledgeReranker,
  downloadKnowledgeEmbedder,
  downloadKnowledgeReranker,
  listKnowledgeEmbedders,
  listKnowledgeRerankers,
  type LocalEmbedderRow,
  type LocalRerankerRow
} from '$lib/api/knowledge';
import type { ToastKind } from '$lib/ui/toast-types';

type Notify = (kind: ToastKind, message: string) => void;

export function createLocalModelDownloads(notify: Notify) {
  let localEmbedders = $state<LocalEmbedderRow[]>([]);
  let localRerankers = $state<LocalRerankerRow[]>([]);
  let embedderDownloading = $state<string | null>(null);
  let rerankerDownloading = $state<string | null>(null);

  // Model ids currently being polled by this browser session (so resume + click never double-poll
  // the same download). The download itself runs server-side regardless.
  const polling = new Set<string>();

  const embedderBusy = $derived(
    embedderDownloading !== null || localEmbedders.some((m) => m.status === 'downloading')
  );
  // True while any local reranker download is in flight (click-initiated this session OR resumed from
  // the server on load) — gates starting a second download.
  const rerankerBusy = $derived(
    rerankerDownloading !== null || localRerankers.some((m) => m.status === 'downloading')
  );

  async function pollReranker(modelId: string, notifyOnDone: boolean) {
    if (polling.has(modelId)) return;
    polling.add(modelId);
    try {
      // The download runs in a server-side subprocess; poll status + byte progress until it resolves.
      // Each poll refreshes the registry rows so percent/status stay live in the UI.
      for (let i = 0; i < 1200; i++) {
        const refreshed = await listKnowledgeRerankers();
        localRerankers = refreshed.data.local ?? localRerankers;
        const row = localRerankers.find((m) => m.id === modelId);
        if (!row || row.downloaded || row.status === 'ready') {
          if (notifyOnDone) notify('success', 'Reranker downloaded.');
          return;
        }
        if (row.status === 'error') {
          if (notifyOnDone) notify('error', row.error || 'Reranker download failed.');
          return;
        }
        // Anything other than 'downloading' (e.g. cancelled → 'available') ends the poll.
        if (row.status !== 'downloading') return;
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    } catch {
      // Transient fetch error while polling — stop quietly; the next page load resumes.
    } finally {
      polling.delete(modelId);
    }
  }

  async function downloadReranker(modelId: string) {
    if (rerankerDownloading) return;
    rerankerDownloading = modelId;
    try {
      await downloadKnowledgeReranker(modelId);
      await pollReranker(modelId, true);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Reranker download failed.');
    } finally {
      rerankerDownloading = null;
    }
  }

  // On page load (or catalog reload), resume the live progress poll for any download still running
  // server-side — so returning to the page shows a ticking bar without a refresh.
  function resumeRerankerPolling() {
    for (const row of localRerankers) {
      if (row.status === 'downloading') void pollReranker(row.id, false);
    }
  }

  async function cancelReranker(modelId: string) {
    try {
      await cancelKnowledgeReranker(modelId);
      const refreshed = await listKnowledgeRerankers();
      localRerankers = refreshed.data.local ?? localRerankers;
      notify('info', 'Download cancelled.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Cancel failed.');
    }
  }

  // Local embedder downloads — same lifecycle as rerankers (poll status + byte progress).
  async function pollEmbedder(modelId: string, notifyOnDone: boolean) {
    if (polling.has(modelId)) return;
    polling.add(modelId);
    try {
      for (let i = 0; i < 1200; i++) {
        const refreshed = await listKnowledgeEmbedders();
        localEmbedders = refreshed.data.local ?? localEmbedders;
        const row = localEmbedders.find((m) => m.id === modelId);
        if (!row || row.downloaded || row.status === 'ready') {
          if (notifyOnDone) notify('success', 'Embedder downloaded.');
          return;
        }
        if (row.status === 'error') {
          if (notifyOnDone) notify('error', row.error || 'Embedder download failed.');
          return;
        }
        if (row.status !== 'downloading') return;
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    } catch {
      // Transient fetch error while polling — stop quietly; the next page load resumes.
    } finally {
      polling.delete(modelId);
    }
  }

  async function downloadEmbedder(modelId: string) {
    if (embedderDownloading) return;
    embedderDownloading = modelId;
    try {
      await downloadKnowledgeEmbedder(modelId);
      await pollEmbedder(modelId, true);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Embedder download failed.');
    } finally {
      embedderDownloading = null;
    }
  }

  function resumeEmbedderPolling() {
    for (const row of localEmbedders) {
      if (row.status === 'downloading') void pollEmbedder(row.id, false);
    }
  }

  async function cancelEmbedder(modelId: string) {
    try {
      await cancelKnowledgeEmbedder(modelId);
      const refreshed = await listKnowledgeEmbedders();
      localEmbedders = refreshed.data.local ?? localEmbedders;
      notify('info', 'Download cancelled.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Cancel failed.');
    }
  }

  /** Seed the status rows from already-fetched payloads and resume any in-flight downloads. */
  function seedFromLoad(rerankers: LocalRerankerRow[], embedders: LocalEmbedderRow[]) {
    localRerankers = rerankers;
    localEmbedders = embedders;
    resumeRerankerPolling();
    resumeEmbedderPolling();
  }

  /** Initial load: fetch the embedder/reranker status rows, then seed + resume. */
  async function load() {
    const [rerankPayload, embedderPayload] = await Promise.all([
      listKnowledgeRerankers(),
      listKnowledgeEmbedders()
    ]);
    seedFromLoad(rerankPayload.data.local ?? [], embedderPayload.data.local ?? []);
  }

  return {
    get localEmbedders() {
      return localEmbedders;
    },
    get localRerankers() {
      return localRerankers;
    },
    get embedderDownloading() {
      return embedderDownloading;
    },
    get rerankerDownloading() {
      return rerankerDownloading;
    },
    get embedderBusy() {
      return embedderBusy;
    },
    get rerankerBusy() {
      return rerankerBusy;
    },
    downloadReranker,
    cancelReranker,
    downloadEmbedder,
    cancelEmbedder,
    load
  };
}
