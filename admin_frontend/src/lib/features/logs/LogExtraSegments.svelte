<script lang="ts">
  import type { LogExtraSegment } from '$lib/api/logs';

  type Props = {
    segments: LogExtraSegment[];
    /** ``table``: inline cell + hover tooltip (parent cell should use class ``group``); ``detail``: detail panel blocks. */
    variant: 'table' | 'detail';
  };

  let { segments, variant }: Props = $props();
</script>

{#snippet kvLine(segment: LogExtraSegment)}
  {#if segment.key}
    <span class="text-[var(--brand-green)]">{segment.key}</span><span class="mx-px opacity-60">=</span><span
      class="text-primary">{segment.value}</span
    >
  {:else}
    <span class="text-primary">{segment.value}</span>
  {/if}
{/snippet}

{#if variant === 'table'}
  {#each segments as segment (segment)}
    <span class="mr-1.5 inline text-xs last:mr-0">{@render kvLine(segment)}</span>
  {/each}
  {#if segments.length > 0}
    <div
      class="fixed z-50 hidden max-w-[500px] translate-y-5 whitespace-normal break-words rounded-md border border-border bg-popover px-3 py-2 text-sm leading-snug text-popover-foreground shadow-xl group-hover:block"
    >
      {#each segments as segment (segment)}
        <div class="block [&+&]:mt-1">{@render kvLine(segment)}</div>
      {/each}
    </div>
  {/if}
{:else if segments.length > 0}
  {#each segments as segment (segment)}
    <div class="mt-2">
      <span class="block text-[0.68rem] font-bold uppercase text-muted-foreground">
        {segment.key ?? 'value'}
      </span>
      {#if segment.pretty}
        <pre
          class="mt-1 whitespace-pre-wrap break-words rounded-md bg-muted/70 px-[0.65rem] py-2 font-mono text-[0.82rem] leading-snug"
        >{segment.pretty}</pre>
      {:else}
        <p class="mt-1 whitespace-pre-wrap break-words text-[0.82rem]">
          {segment.value || '-'}
        </p>
      {/if}
    </div>
  {/each}
{:else}
  <p class="text-[0.82rem]">-</p>
{/if}
