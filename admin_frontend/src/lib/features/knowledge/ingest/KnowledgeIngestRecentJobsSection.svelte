<script lang="ts">
  import { ChevronRight } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import type { KnowledgeIngestModel } from '$lib/features/knowledge/state/knowledge-ingest.svelte';
  import { formatJobTotalsSummary } from '$lib/features/knowledge/shared/knowledge-pure';
  import { KNOWLEDGE_SECTION_CARD, KNOWLEDGE_SECTION_TITLE } from '$lib/features/knowledge/shared/knowledge-ui';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    ingest: KnowledgeIngestModel;
    expanded?: boolean;
    headerSummary: string;
  };

  let { ingest, expanded = $bindable(), headerSummary }: Props = $props();

  const RECENT_JOBS_BODY_ID = 'knowledge-ingest-recent-jobs';
</script>

<section class={KNOWLEDGE_SECTION_CARD}>
  <div class="grid gap-3">
    <div class="flex items-start justify-between gap-2">
      <button
        type="button"
        class="flex min-w-0 flex-1 items-start gap-2 rounded-md py-0.5 text-left outline-none transition hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
        aria-expanded={expanded}
        aria-controls={RECENT_JOBS_BODY_ID}
        onclick={() => {
          expanded = !expanded;
        }}
      >
        <ChevronRight
          size={18}
          class={cn(
            'mt-0.5 shrink-0 text-muted-foreground transition-transform duration-150',
            expanded && 'rotate-90'
          )}
          aria-hidden="true"
        />
        <span class={KNOWLEDGE_SECTION_TITLE}>Recent jobs</span>
      </button>
      <span class="shrink-0 text-right font-sans text-xs text-muted-foreground">{headerSummary}</span>
    </div>
    <div id={RECENT_JOBS_BODY_ID} class="grid gap-2" hidden={!expanded}>
      {#each ingest.recentJobs as item (item.id)}
        <div class="flex flex-wrap items-center gap-2 rounded-md border bg-background p-2 font-sans text-xs text-muted-foreground">
          <Badge variant={item.status === 'completed' ? 'success' : item.status === 'failed' ? 'destructive' : 'outline'}>
            {item.status}
          </Badge>
          <span>{formatChatTimestamp(item.created_at)}</span>
          <span>{formatJobTotalsSummary(item.totals)}</span>
          {#if item.status === 'failed'}
            <Button class="h-7" type="button" variant="outline" onclick={() => void ingest.retryJob(item)} disabled={ingest.ingesting}>
              Retry
            </Button>
          {/if}
          {#if Object.keys(item.errors).length > 0}
            <Button
              class="h-7"
              type="button"
              variant="outline"
              onclick={() => ingest.toggleActiveErrorsJobId(item.id)}
            >
              View errors
            </Button>
          {/if}
          {#if ingest.activeErrorsJobId === item.id}
            <details class="basis-full text-xs" open>
              <summary class="text-destructive">Errors</summary>
              <InlineDestructiveAlert
                class="mt-2 whitespace-pre-wrap font-mono text-xs"
                message={JSON.stringify(item.errors, null, 2)}
              />
            </details>
          {/if}
        </div>
      {/each}
    </div>
  </div>
</section>
