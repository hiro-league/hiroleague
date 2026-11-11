<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import { Brain, Database } from '@lucide/svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import type { PageTab } from '$kit/ui/page-tabs.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import EvalPanel from '$lib/features/eval/EvalPanel.svelte';
  import LiveDegradedBanner from '$lib/live/LiveDegradedBanner.svelte';
  import { createEvalPreferences } from '$lib/preferences/eval-preferences.svelte';
  import { toast } from '$kit/ui/toast.svelte';
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
  } as const satisfies Record<EvalTrack, PageTab<EvalTrack>['icon']>;

  // Switching the track resets the corpus picker + rescans, so lock the tabs while a
  // run is in flight (mirrors the inline pill tablist this strip replaced).
  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  const tabDescriptors: PageTab<EvalTrack>[] = $derived([
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

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Eval" description="Memory & knowledge retrieval evals">
    {#snippet tabs()}
    <PageTabs
      label="Eval track"
      tabs={tabDescriptors}
      value={eval_.track}
      onchange={selectTrack}
    />
    {/snippet}
  </PageHeader>
  

  {#if error}
    <Notice message={error} />
  {/if}

  <LiveDegradedBanner />

  <EvalPanel {eval_} notify={toast.show} />
</section>

