/**
 * Eval corpus-picker sub-controller — track-agnostic corpus context shared by every sub-tab:
 * the scanned-folder corpus list (+ benchmark grouping), the chosen corpus, its question bank +
 * checklist selection, and the memory-track episode transcript (+ per-episode extraction). It
 * owns none of the run options or saved-results surface; those siblings are reached through the
 * injected `EvalCorpusPickerDeps` callbacks (`onCorpusResolved` / `reloadResults`).
 */
import {
  getCorpusIngestExtraction,
  getEvalCorpus,
  listEvalCorpuses,
  listEvalQuestions,
  pickKnowledgeFolder,
  type CorpusEpisodeExtraction,
  type EvalCorpus,
  type EvalEpisode,
  type EvalQuestionItem
} from '$lib/api/knowledge';
import { PREF_KEYS } from '$lib/preferences/keys';
import { readCorpusPref, writeCorpusPref } from '$lib/features/eval/shared/eval-prefs';
import { listBenchmarks, visibleCorpusesFor } from '$lib/features/eval/shared/eval-corpus';
import type { EvalTrack } from '$lib/features/eval/shared/eval-row';

/** Narrow seam to the sibling sub-controllers (setup + memory results), injected by the facade. */
export type EvalCorpusPickerDeps = {
  getTrack: () => EvalTrack;
  setError: (message: string | null) => void;
  /** A corpus was (re)selected — restore its per-corpus setup (answer prompt + rebuild default). */
  onCorpusResolved: () => void;
  /** Reload the corpus's saved results / coverage badges (memory-results sub-controller). */
  reloadResults: () => void;
};

export function createEvalCorpusPicker(deps: EvalCorpusPickerDeps) {
  // Corpus picker — a folder (text + native pick, like Knowledge Add), a scanned corpus
  // list, and the chosen corpus. Folder persists across reloads.
  let folder = $state<string>(localStorage.getItem(PREF_KEYS.evalFolder) ?? '');
  let corpuses = $state<EvalCorpus[]>([]);
  // Absolute workspace ``logs/`` dir (ledger sidecar root) from the corpus scan. The "Copy for AI"
  // brief uses it to point an agent at retrieval_trace/ingest_trace/graph.log without searching.
  // '' until the first scan resolves (or if the workspace can't be resolved) → brief falls back
  // to relative paths. Workspace-global, so it survives track/corpus switches.
  let logDir = $state<string>('');
  let corpusesLoading = $state(false);
  let corpusesError = $state<string | null>(null);
  let pickingFolder = $state(false);
  let selectedCorpusId = $state<string>('');

  // Question bank of the chosen corpus.
  let questions = $state<EvalQuestionItem[]>([]);
  let questionsLoading = $state(false);
  let questionsError = $state<string | null>(null);

  // Selected question ids — explicit; NO cap, and an empty set blocks the run.
  let selected = $state<Set<string>>(new Set());

  // Corpus review (memory track only) — the chosen corpus's episodes rendered as a readable
  // transcript above the questions, plus light meta (count + date span) for the stats header.
  // Knowledge corpora are folders of .md docs, not episode turns, so this stays empty there.
  let corpusEpisodes = $state<EvalEpisode[]>([]);
  let corpusMeta = $state<{
    episode_count: number;
    first_timestamp: string;
    last_timestamp: string;
  } | null>(null);
  let corpusLoading = $state(false);
  let corpusError = $state<string | null>(null);
  // Per-episode at-ingest extraction (entity/fact counts + ingest-trace pointer), keyed by episode
  // id — drives the Corpus tab's extracted/not badge + "ingest pipeline" button. Empty when the
  // corpus was remembered with graph tracing off (observability !== 'trace') or not yet ingested.
  let corpusExtraction = $state<Record<string, CorpusEpisodeExtraction>>({});
  // The corpus's eval graph partition (e.g. `eval_mem_beam128k_13`), from the extraction load —
  // used to deep-link an episode into the graph view (group + chunk_id filter). '' until loaded.
  let corpusExtractionGroup = $state<string>('');

  const selectedCorpus = (): EvalCorpus | null =>
    corpuses.find((c) => c.id === selectedCorpusId) ?? null;

  /** The benchmark of the currently selected corpus ('' on the knowledge track / no selection). */
  const selectedBenchmarkId = (): string => selectedCorpus()?.benchmark ?? '';

  /** Scan the chosen folder for this track's corpuses; auto-select the first. */
  async function scanCorpuses() {
    const track = deps.getTrack();
    corpusesLoading = true;
    corpusesError = null;
    try {
      const res = await listEvalCorpuses(track, folder.trim());
      corpuses = res.data.corpuses ?? [];
      // Keep the resolved logs/ dir if present; never clobber a good value with an empty one
      // (a degraded scan shouldn't wipe a path the brief already has).
      if (res.data.log_dir) logDir = res.data.log_dir;
      // Keep the folder the server resolved (so the default eval/ path shows in the field).
      if (!folder.trim() && res.data.folder) folder = res.data.folder;
      // Prefer the current in-session selection, else the persisted one (fresh load),
      // else the first corpus. Only ids that still exist in the scanned list survive.
      const desired = selectedCorpusId || readCorpusPref(track);
      const keep = corpuses.find((c) => c.id === desired);
      selectedCorpusId = keep ? keep.id : (corpuses[0]?.id ?? '');
      if (selectedCorpusId) writeCorpusPref(track, selectedCorpusId);
      // Restore this corpus's per-corpus setup (answer prompt + Rebuild-graph default).
      deps.onCorpusResolved();
      await loadQuestions();
    } catch (err) {
      corpusesError = err instanceof Error ? err.message : 'Failed to scan corpuses.';
      corpuses = [];
      selectedCorpusId = '';
      questions = [];
    } finally {
      corpusesLoading = false;
    }
  }

  async function browseFolder() {
    pickingFolder = true;
    deps.setError(null);
    try {
      const res = await pickKnowledgeFolder(folder.trim() || undefined);
      if (res.data.folder) {
        setFolder(res.data.folder);
        await scanCorpuses();
      }
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Folder picker failed.');
    } finally {
      pickingFolder = false;
    }
  }

  function setFolder(v: string) {
    folder = v;
    localStorage.setItem(PREF_KEYS.evalFolder, v);
  }

  /** Load the chosen corpus's episodes for the Corpus review panel (memory track only).
   *  Independent of the question bank, so it runs even when the bank is missing. Clears
   *  to empty on the knowledge track (its corpora are .md folders, not episode turns). */
  async function loadCorpus() {
    corpusEpisodes = [];
    corpusMeta = null;
    corpusError = null;
    corpusExtraction = {};
    corpusExtractionGroup = '';
    if (deps.getTrack() !== 'memory') return;
    const corpus = selectedCorpus();
    if (!corpus || !corpus.corpus_path) return;
    corpusLoading = true;
    try {
      const res = await getEvalCorpus(corpus.corpus_path);
      corpusEpisodes = res.data.episodes ?? [];
      corpusMeta = {
        episode_count: res.data.episode_count,
        first_timestamp: res.data.first_timestamp,
        last_timestamp: res.data.last_timestamp
      };
    } catch (err) {
      corpusError = err instanceof Error ? err.message : 'Failed to load corpus episodes.';
    } finally {
      corpusLoading = false;
    }
    // Per-episode extraction is best-effort enrichment (separate ingest-trace source): a failure
    // or an untraced corpus just leaves the counts/button off — never blocks the transcript.
    void loadCorpusExtraction(corpus.id);
  }

  /** Load the corpus's per-episode at-ingest extraction counts (+ ingest-trace pointers) from its
   *  ingest-trace sidecars. Best-effort: a failure clears the map rather than surfacing an error. */
  async function loadCorpusExtraction(corpusId: string) {
    try {
      const res = await getCorpusIngestExtraction(corpusId);
      // Only apply if the user hasn't switched corpus mid-flight (the episodes are this corpus's).
      if (selectedCorpus()?.id === corpusId) {
        corpusExtraction = res.data?.episodes ?? {};
        corpusExtractionGroup = res.data?.group_id ?? '';
      }
    } catch (err) {
      console.warn('eval corpus extraction load failed', err);
      if (selectedCorpus()?.id === corpusId) {
        corpusExtraction = {};
        corpusExtractionGroup = '';
      }
    }
  }

  /** Load the chosen corpus's question bank; clears the prior selection. Refreshes the corpus
   *  transcript + saved results alongside, so every entry point (scan / select / reload) keeps
   *  the bank, transcript, and coverage badges in sync. */
  async function loadQuestions() {
    void loadCorpus();
    deps.reloadResults();
    selected = new Set();
    const corpus = selectedCorpus();
    if (!corpus || !corpus.questions_path) {
      questions = [];
      questionsError =
        corpus && !corpus.questions_path
          ? `No question bank (${corpus.id}.questions.yaml) found beside this corpus.`
          : null;
      return;
    }
    questionsLoading = true;
    questionsError = null;
    try {
      const res = await listEvalQuestions(corpus.questions_path);
      questions = res.data.questions ?? [];
    } catch (err) {
      questionsError = err instanceof Error ? err.message : 'Failed to load questions.';
      questions = [];
    } finally {
      questionsLoading = false;
    }
  }

  /** Commit a new selected corpus id + persist it per track. The facade owns the surrounding
   *  run-reset / confirm flow (selectCorpus); this is the pure state write it calls afterwards. */
  function setSelectedCorpusId(id: string) {
    selectedCorpusId = id;
    writeCorpusPref(deps.getTrack(), id);
  }

  /** Reset the corpus-scoped state on a track switch / re-init (before the new track's rescan). */
  function resetForTrack() {
    selectedCorpusId = '';
    questions = [];
    selected = new Set();
  }

  function toggleQuestion(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected = next;
  }

  /** Select/deselect a whole category's ids (no cap). */
  function setCategorySelected(ids: string[], on: boolean) {
    const next = new Set(selected);
    for (const id of ids) {
      if (on) next.add(id);
      else next.delete(id);
    }
    selected = next;
  }

  function clearSelection() {
    selected = new Set();
  }

  /** Select every question in the loaded bank (no cap). */
  function selectAll() {
    selected = new Set(questions.map((q) => q.id));
  }

  return {
    get folder() {
      return folder;
    },
    setFolder,
    browseFolder,
    scanCorpuses,
    get pickingFolder() {
      return pickingFolder;
    },
    get corpuses() {
      return corpuses;
    },
    // Benchmark grouping (memory track) — corpuses arrive from the server pre-grouped + ordered by
    // eval/benchmarks.yaml; the selected benchmark is derived from the selected corpus (single
    // source of truth = selectedCorpusId). Knowledge corpuses carry no benchmark → empty list.
    get benchmarks() {
      return listBenchmarks(corpuses);
    },
    get selectedBenchmarkId() {
      return selectedBenchmarkId();
    },
    get visibleCorpuses() {
      return visibleCorpusesFor(corpuses, selectedBenchmarkId());
    },
    get corpusesLoading() {
      return corpusesLoading;
    },
    get corpusesError() {
      return corpusesError;
    },
    get selectedCorpusId() {
      return selectedCorpusId;
    },
    get logDir() {
      return logDir;
    },
    get selectedCorpus() {
      return selectedCorpus();
    },
    setSelectedCorpusId,
    resetForTrack,
    loadQuestions,
    loadCorpus,
    get questions() {
      return questions;
    },
    get questionsLoading() {
      return questionsLoading;
    },
    get questionsError() {
      return questionsError;
    },
    get corpusEpisodes() {
      return corpusEpisodes;
    },
    get corpusExtraction() {
      return corpusExtraction;
    },
    get corpusExtractionGroup() {
      return corpusExtractionGroup;
    },
    get corpusMeta() {
      return corpusMeta;
    },
    get corpusLoading() {
      return corpusLoading;
    },
    get corpusError() {
      return corpusError;
    },
    // Checklist selection (no cap; an empty set blocks a question run).
    get selectedCount() {
      return selected.size;
    },
    get selectedIds(): string[] {
      return [...selected];
    },
    isSelected: (id: string) => selected.has(id),
    toggleQuestion,
    setCategorySelected,
    clearSelection,
    selectAll
  };
}

export type EvalCorpusPicker = ReturnType<typeof createEvalCorpusPicker>;
