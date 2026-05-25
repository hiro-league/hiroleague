<script lang="ts">
  import { LoaderCircle } from '@lucide/svelte';
  import type { KnowledgeDocument, KnowledgeJobData } from '$lib/api/knowledge';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import KnowledgeAffectedDocumentsList from '$lib/features/knowledge/browse/KnowledgeAffectedDocumentsList.svelte';
  import type { KnowledgeIngestModel } from '$lib/features/knowledge/state/knowledge-ingest.svelte';
  import { jobElapsed } from '$lib/features/knowledge/shared/knowledge-pure';
  import {
    KNOWLEDGE_BROWSE_BULK_DIALOG,
    KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST,
    KNOWLEDGE_BROWSE_BULK_DIALOG_BODY
  } from '$lib/features/knowledge/shared/knowledge-ui';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';

  type Props = {
    open: boolean;
    documents: KnowledgeDocument[];
    ingest: KnowledgeIngestModel;
  };

  type Phase = 'confirm' | 'running' | 'done';

  type DocumentResult = {
    document: KnowledgeDocument;
    status: KnowledgeJobData['status'] | 'start_failed' | 'timeout';
    job: KnowledgeJobData | null;
  };

  let { open = $bindable(false), documents = [], ingest }: Props = $props();

  let phase = $state<Phase>('confirm');
  let targetJobId = $state<string | null>(null);
  let startError = $state<string | null>(null);
  let starting = $state(false);
  let currentIndex = $state(0);
  let results = $state<DocumentResult[]>([]);

  const documentCount = $derived(documents.length);
  const currentDocument = $derived(documents[currentIndex] ?? null);
  const trackedJob = $derived(
    targetJobId && ingest.job?.job_id === targetJobId ? ingest.job : null
  );
  const trackedJobRecord = $derived(
    targetJobId ? (ingest.recentJobs.find((item) => item.id === targetJobId) ?? null) : null
  );
  const jobTotal = $derived(Math.max(1, trackedJob?.totals.requested ?? 1));
  const jobDone = $derived(
    (trackedJob?.totals.ingested ?? 0) +
      (trackedJob?.totals.skipped ?? 0) +
      (trackedJob?.totals.failed ?? 0)
  );
  const jobPercent = $derived(Math.min(100, Math.round((jobDone / jobTotal) * 100)));
  const completedCount = $derived(results.length);
  const successCount = $derived(results.filter((result) => result.status === 'completed').length);
  const failedCount = $derived(
    results.filter((result) => result.status !== 'completed').length
  );

  $effect(() => {
    if (!open) {
      phase = 'confirm';
      targetJobId = null;
      startError = null;
      starting = false;
      currentIndex = 0;
      results = [];
    }
  });

  function waitForJobTerminal(jobId: string): Promise<KnowledgeJobData | null> {
    return new Promise((resolve) => {
      const started = Date.now();
      const interval = setInterval(() => {
        const job = ingest.job;
        if (job?.job_id === jobId && job.status !== 'running') {
          clearInterval(interval);
          resolve(job);
          return;
        }
        if (Date.now() - started > 600_000) {
          clearInterval(interval);
          resolve(null);
        }
      }, 250);
    });
  }

  async function runBulkReingest() {
    if (documents.length === 0 || starting) return;
    starting = true;
    startError = null;
    results = [];
    currentIndex = 0;
    phase = 'running';

    for (let index = 0; index < documents.length; index++) {
      const document = documents[index];
      currentIndex = index;
      targetJobId = null;
      const job = await ingest.reingestActiveDocument(document.id);
      if (!job) {
        results = [
          ...results,
          { document, status: 'start_failed', job: null }
        ];
        continue;
      }
      targetJobId = job.job_id;
      const finishedJob = await waitForJobTerminal(job.job_id);
      results = [
        ...results,
        {
          document,
          status: finishedJob?.status ?? 'timeout',
          job: finishedJob
        }
      ];
    }

    starting = false;
    phase = 'done';
  }

  function closeDialog() {
    open = false;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content
    class={KNOWLEDGE_BROWSE_BULK_DIALOG}
    showCloseButton={phase !== 'running' && !starting}
  >
    <Dialog.Header>
      <Dialog.Title class="break-words">
        {documentCount === 1 ? 'Re-ingest document' : `Re-ingest ${documentCount} documents`}
      </Dialog.Title>
      {#if documentCount > 1}
        <Dialog.Description>
          Documents are re-ingested one at a time. Existing indexed content for each document will be replaced.
        </Dialog.Description>
      {/if}
    </Dialog.Header>

    <div class={KNOWLEDGE_BROWSE_BULK_DIALOG_BODY}>
    {#if phase === 'confirm'}
      <KnowledgeAffectedDocumentsList {documents} class={KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST} />
      <p class="shrink-0 font-sans text-sm leading-relaxed text-muted-foreground">
        This re-parses the source file, rebuilds chunks, and re-embeds them in the knowledge index.
        Existing indexed content {documentCount === 1 ? 'for this document' : 'for each selected document'} will be replaced.
      </p>
      {#if startError}
        <InlineDestructiveAlert class="mt-3" message={startError} />
      {/if}
    {:else if phase === 'running'}
      <div class="grid gap-3 font-sans text-sm">
        {#if documentCount > 1}
          <div class="flex flex-wrap items-center gap-2 text-muted-foreground">
            <span>
              Document {currentIndex + 1} of {documentCount}
            </span>
            {#if currentDocument}
              <span class="truncate font-medium text-foreground">{currentDocument.title}</span>
            {/if}
          </div>
        {/if}
        {#if trackedJob}
          <div class="grid gap-2 rounded-md border bg-background p-3">
            <div class="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{trackedJob.status}</Badge>
              <span class="text-muted-foreground">
                {trackedJob.totals.ingested ?? 0} ingested, {trackedJob.totals.skipped ?? 0} skipped,
                {trackedJob.totals.failed ?? 0} failed, {trackedJob.totals.chunks ?? 0} chunks
              </span>
              {#if trackedJobRecord}
                <span class="text-xs text-muted-foreground">elapsed {jobElapsed(trackedJobRecord.created_at)}</span>
              {/if}
              <span class="ml-auto text-xs text-muted-foreground">
                {jobDone}/{trackedJob.totals.requested ?? 0} files
              </span>
            </div>
            <div class="h-2 overflow-hidden rounded-full bg-muted">
              <div class="h-full bg-primary transition-all" style={`width: ${jobPercent}%`}></div>
            </div>
            {#if trackedJob.in_flight?.length}
              <div class="truncate font-sans text-xs text-muted-foreground" title={trackedJob.in_flight.join(', ')}>
                Processing {trackedJob.in_flight.length} file(s): {trackedJob.in_flight.join(', ')}
              </div>
            {/if}
          </div>
        {:else}
          <div class="flex items-center gap-2 text-muted-foreground">
            <LoaderCircle size={16} class="animate-spin" />
            Starting re-ingest…
          </div>
        {/if}
      </div>
    {:else if phase === 'done'}
      {#if documentCount === 1 && results[0]?.job}
        {@const trackedJob = results[0].job}
        <div class="grid gap-2 rounded-md border bg-background p-3 font-sans text-sm">
          <div class="flex flex-wrap items-center gap-2">
            <Badge
              variant={trackedJob.status === 'completed'
                ? 'success'
                : trackedJob.status === 'failed'
                  ? 'destructive'
                  : 'outline'}
            >
              {trackedJob.status}
            </Badge>
            <span class="text-muted-foreground">
              {trackedJob.totals.ingested ?? 0} ingested, {trackedJob.totals.skipped ?? 0} skipped,
              {trackedJob.totals.failed ?? 0} failed, {trackedJob.totals.chunks ?? 0} chunks
            </span>
          </div>
          {#if Object.keys(trackedJob.errors).length > 0}
            <InlineDestructiveAlert
              title="Re-ingest errors"
              class="whitespace-pre-wrap font-mono text-xs"
              message={JSON.stringify(trackedJob.errors, null, 2)}
            />
          {/if}
        </div>
      {:else if documentCount > 1}
        <div class="grid gap-2 rounded-md border bg-background p-3 font-sans text-sm">
          <div class="flex flex-wrap items-center gap-2">
            <Badge variant={failedCount === 0 ? 'success' : successCount === 0 ? 'destructive' : 'outline'}>
              {successCount} completed, {failedCount} failed
            </Badge>
            <span class="text-muted-foreground">{completedCount} of {documentCount} processed</span>
          </div>
          <ul class="min-h-0 flex-1 space-y-1 overflow-y-auto text-sm">
            {#each results as result (result.document.id)}
              <li class="flex flex-wrap items-center gap-2">
                <Badge
                  variant={result.status === 'completed'
                    ? 'success'
                    : result.status === 'failed' || result.status === 'start_failed'
                      ? 'destructive'
                      : 'outline'}
                >
                  {result.status}
                </Badge>
                <span class="truncate">{result.document.title}</span>
              </li>
            {/each}
          </ul>
        </div>
      {:else if startError}
        <InlineDestructiveAlert message={startError} />
      {/if}
    {/if}
    </div>

    <Dialog.Footer>
      {#if phase === 'confirm'}
        <Button variant="outline" disabled={starting} onclick={closeDialog}>Cancel</Button>
        <Button disabled={starting || documents.length === 0} onclick={() => void runBulkReingest()}>
          {#if starting}
            <LoaderCircle size={16} class="animate-spin" />
          {/if}
          {documentCount === 1 ? 'Re-ingest' : `Re-ingest ${documentCount} documents`}
        </Button>
      {:else if phase === 'running'}
        <Button variant="outline" disabled>Re-ingesting…</Button>
      {:else}
        <Button onclick={closeDialog}>Close</Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
