<script lang="ts">
  import { ChevronRight, Wrench } from '@lucide/svelte';
  import type { AgentToolCall } from '$lib/api/chat-channels';
  import { cn } from '$lib/utils';

  type Props = {
    tools: AgentToolCall[];
  };

  let { tools }: Props = $props();
  let expanded = $state<Record<string, boolean>>({});

  function toolKey(tool: AgentToolCall, index: number): string {
    return tool.id || `${tool.name ?? 'tool'}-${index}`;
  }

  function toggleTool(key: string) {
    expanded = { ...expanded, [key]: !expanded[key] };
  }

  function elapsedLabel(ms: number | undefined): string | null {
    if (typeof ms !== 'number') return null;
    if (ms < 1_000) return `${Math.max(0, Math.round(ms))}ms`;
    return `${(ms / 1_000).toFixed(ms < 10_000 ? 1 : 0).replace(/\.0$/, '')}s`;
  }

  function statusClass(status: string | undefined): string {
    if (status === 'error') return 'text-destructive';
    if (status === 'running') return 'opacity-80';
    return 'opacity-60';
  }
</script>

{#if tools.length > 0}
  <div class="grid gap-1.5 pb-1">
    {#each tools as tool, index (toolKey(tool, index))}
      {@const key = toolKey(tool, index)}
      {@const elapsed = elapsedLabel(tool.elapsed_ms)}
      <div class="overflow-hidden rounded-md border border-current/15 bg-background/20">
        <button
          type="button"
          class="flex w-full min-w-0 items-center gap-1.5 px-2 py-1.5 text-left font-sans text-[11px] leading-tight"
          aria-expanded={Boolean(expanded[key])}
          onclick={() => toggleTool(key)}
        >
          <ChevronRight
            size={13}
            class={cn('shrink-0 transition-transform', expanded[key] && 'rotate-90')}
          />
          <Wrench size={12} class="shrink-0 opacity-65" />
          <span class="min-w-0 flex-1 truncate font-medium">{tool.name || 'tool'}</span>
          {#if elapsed}
            <span class="shrink-0 tabular-nums opacity-55">{elapsed}</span>
          {/if}
          <span class={cn('shrink-0 uppercase tracking-normal', statusClass(tool.status))}>
            {tool.status || 'done'}
          </span>
        </button>
        {#if expanded[key]}
          <dl class="grid gap-1 border-current/10 border-t px-2 py-1.5 font-mono text-[10px] leading-snug opacity-75">
            {#if tool.id}
              <div class="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2">
                <dt>id</dt>
                <dd class="min-w-0 break-all">{tool.id}</dd>
              </div>
            {/if}
            <div class="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2">
              <dt>status</dt>
              <dd>{tool.status || 'done'}</dd>
            </div>
            {#if elapsed}
              <div class="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2">
                <dt>elapsed</dt>
                <dd>{elapsed}</dd>
              </div>
            {/if}
            {#if tool.error}
              <div class="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2 text-destructive">
                <dt>error</dt>
                <dd class="min-w-0 whitespace-pre-wrap break-words">{tool.error}</dd>
              </div>
            {/if}
          </dl>
        {/if}
      </div>
    {/each}
  </div>
{/if}
