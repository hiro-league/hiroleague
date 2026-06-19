<script lang="ts">
  import type { KnowledgeScannedFile } from '$lib/api/knowledge';
  import KnowledgeFilePreviewDialog from '$lib/features/knowledge/shared/file-preview/KnowledgeFilePreviewDialog.svelte';
  import KnowledgeIngestFormSection from '$lib/features/knowledge/ingest/KnowledgeIngestFormSection.svelte';
  import KnowledgeIngestRecentJobsSection from '$lib/features/knowledge/ingest/KnowledgeIngestRecentJobsSection.svelte';
  import KnowledgeIngestScanSection from '$lib/features/knowledge/ingest/KnowledgeIngestScanSection.svelte';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import { formatIngestHeaderSummary, formatRecentJobsHeaderSummary } from '$lib/features/knowledge/shared/knowledge-pure';

  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();
  const ingest = $derived(ctl.ingest);
  const options = $derived(ctl.options);

  let previewOpen = $state(false);
  let previewFile = $state<KnowledgeScannedFile | null>(null);
  let recentJobsExpanded = $state(false);
  let ingestSectionExpanded = $state(false);

  function openFilePreview(file: KnowledgeScannedFile) {
    previewFile = file;
    previewOpen = true;
  }

  const ingestHeaderSummary = $derived(
    formatIngestHeaderSummary(ingest.selectedPaths.length, ingest.job?.status ?? null)
  );
  const recentJobsHeaderSummary = $derived(formatRecentJobsHeaderSummary(ingest.recentJobs));

  $effect(() => {
    if (ingest.ingesting || ingest.job?.status === 'running') {
      ingestSectionExpanded = true;
    }
  });
</script>

<section class="grid gap-4">
  <KnowledgeIngestScanSection {ingest} onPreviewFile={openFilePreview} />

  <KnowledgeIngestFormSection
    {ctl}
    {ingest}
    {options}
    bind:expanded={ingestSectionExpanded}
    headerSummary={ingestHeaderSummary}
  />

  {#if ingest.recentJobs.length > 0}
    <KnowledgeIngestRecentJobsSection
      {ingest}
      bind:expanded={recentJobsExpanded}
      headerSummary={recentJobsHeaderSummary}
    />
  {/if}
</section>

<KnowledgeFilePreviewDialog bind:open={previewOpen} file={previewFile} />
