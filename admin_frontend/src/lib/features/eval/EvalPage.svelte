<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import { Brain, Database } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import EvalPanel from '$lib/features/eval/EvalPanel.svelte';
  import { knowledgeEventStream } from '$lib/features/knowledge/shared/knowledge-event-stream.svelte';
  import { createEvalPreferences } from '$lib/preferences/eval-preferences.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import {
    createEvalModel,
    type EvalTrack
  } from '$lib/features/eval/state/eval-model.svelte';

  /**
   * Top-level Eval page. Thin composition root: it owns the shared error banner,
   * the Memory/Knowledge track as first-level page tabs (URL `?tab=` + session
   * persistence, like every other admin page), and the eval model — which it
   * passes down to the panel view. The model owns all eval transport/state and
   * reuses the shared knowledge SSE stream.
   */
  let error = $state<string | null>(null);
  const tabPrefs = createEvalPreferences();
  const toasts = createToastNotifier();
  const eval_ = createEvalModel({ setError: (msg) => (error = msg) });

  onMount(() => {
    tabPrefs.initialize();
    // Start on the persisted / deep-linked track; init() runs the single corpus scan.
    // If a LIVE run pulls the model to a different track (cross-origin mid-run
    // hydrate), follow it so the URL/session stays honest with what's shown.
    void eval_.init(tabPrefs.activeTab).then(() => {
      if (eval_.track !== tabPrefs.activeTab) void tabPrefs.setActiveTab(eval_.track);
    });
    return () => eval_.teardown();
  });

  afterNavigate(() => {
    tabPrefs.syncActiveTabFromUrl();
    // Mirror browser back/forward tab changes into the model (the live track owner).
    if (tabPrefs.activeTab !== eval_.track) eval_.setTrack(tabPrefs.activeTab);
  });

  const trackTabIcons = {
    memory: Brain,
    knowledge: Database
  } as const satisfies Record<EvalTrack, AdminTabDescriptor<EvalTrack>['icon']>;

  // Switching the track resets the corpus picker + rescans, so lock the tabs while a
  // run is in flight (mirrors the inline pill tablist this strip replaced).
  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  const tabDescriptors: AdminTabDescriptor<EvalTrack>[] = $derived([
    { id: 'memory', label: 'Memory', kind: 'pane', icon: trackTabIcons.memory, disabled: isBusy },
    { id: 'knowledge', label: 'Knowledge', kind: 'pane', icon: trackTabIcons.knowledge, disabled: isBusy }
  ]);

  function selectTrack(id: EvalTrack) {
    eval_.setTrack(id);
    void tabPrefs.setActiveTab(id);
  }
</script>

<svelte:head>
  <title>Eval - Hiro Admin</title>
</svelte:head>

<AdminPageHeader
  kicker="Evaluation"
  title="Eval"
  subtitle="Memory & knowledge retrieval evals"
  sticky
>
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel="Eval track"
      tabs={tabDescriptors}
      active={eval_.track}
      onSelect={selectTrack}
    />
  {/snippet}

  {#if error}
    <InlineDestructiveAlert message={error} />
  {/if}

  <!-- Live-events connection health. `degraded` flips on when the single shared SSE
       stream can't (re)connect within its grace window — most often the browser's
       per-origin connection budget is exhausted by too many open admin tabs. We say so
       explicitly rather than letting live updates silently stop / requests freeze. -->
  {#if knowledgeEventStream.degraded}
    <div
      role="status"
      class="mb-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300"
    >
      Live updates are disconnected — the browser may be out of connections. Close some
      other Hiro Admin browser tabs and they’ll resume automatically.
    </div>
  {/if}

  <EvalPanel {eval_} notify={toasts.notify} />
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
