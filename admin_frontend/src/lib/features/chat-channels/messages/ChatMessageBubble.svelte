<script lang="ts">
  import { fly } from 'svelte/transition';
  import { Volume2 } from '@lucide/svelte';
  import {
    historyMessageFirstAudio,
    historyMessageText,
    type AgentMessageMetadata,
    type ChatHistoryMessage
  } from '$lib/api/chat-channels';
  import ChatMessageAttachmentAudio from '$lib/features/chat-channels/ChatMessageAttachmentAudio.svelte';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import AgentTokenCounter from '$lib/features/chat-channels/messages/AgentTokenCounter.svelte';
  import AgentToolStack from '$lib/features/chat-channels/messages/AgentToolStack.svelte';
  import {
    agentCostLabel,
    agentElapsedLabel,
    agentInputTokensIncludingCached,
    agentOutputTokens,
    agentTokensShouldAnimate,
    agentTools,
    resolveAgentMetadata,
    shouldShowAgentTelemetry,
    telemetryBreakdownTitle
  } from '$lib/features/chat-channels/messages/agent-message-meta';
  import { cn } from '$lib/utils';

  type Props = {
    message: ChatHistoryMessage;
    /** All messages in the thread — used to dedupe telemetry across a user/agent pair. */
    messages: ChatHistoryMessage[];
    /** Inbound (user) agent metadata indexed by `reply_id`. */
    inboundAgentMetaByReplyId: Map<string, AgentMessageMetadata>;
    selectedChannelId: string | null;
    agentVoiceGeneratingMessageId: string | null;
    showAgentTokensUi: boolean;
    showAgentToolsUi: boolean;
  };

  let {
    message,
    messages,
    inboundAgentMetaByReplyId,
    selectedChannelId,
    agentVoiceGeneratingMessageId,
    showAgentTokensUi,
    showAgentToolsUi
  }: Props = $props();

  const isUser = $derived(message.sender_type === 'user');
  const textBody = $derived(historyMessageText(message));
  const audioItem = $derived(historyMessageFirstAudio(message));
  const agentMeta = $derived(resolveAgentMetadata(message, isUser, inboundAgentMetaByReplyId));
  const showAgentMeta = $derived(shouldShowAgentTelemetry(message, agentMeta, isUser, messages));
  const outputTokens = $derived(showAgentMeta ? agentOutputTokens(agentMeta) : 0);
  const inputTokensIncl = $derived(showAgentMeta ? agentInputTokensIncludingCached(agentMeta) : 0);
  const toolCalls = $derived(showAgentMeta ? agentTools(agentMeta) : []);
  const tokenCountAnimates = $derived(showAgentMeta && agentTokensShouldAnimate(agentMeta));
  const costLabel = $derived(showAgentMeta ? agentCostLabel(agentMeta) : '');
  const elapsedLabel = $derived(showAgentMeta ? agentElapsedLabel(agentMeta) : '');
  const tokenTooltip = $derived(telemetryBreakdownTitle(agentMeta?.usage_total));
  const showToolsUi = $derived(showAgentToolsUi && toolCalls.length > 0);
  const showTokensUi = $derived(
    showAgentTokensUi && (outputTokens > 0 || inputTokensIncl > 0 || Boolean(costLabel) || Boolean(elapsedLabel))
  );
</script>

<div class={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')} in:fly={{ y: 8, duration: 160 }}>
  <div
    class={cn(
      'grid max-w-[85%] gap-1.5 rounded-2xl px-4 py-2.5 shadow-sm',
      isUser
        ? 'bg-primary text-primary-foreground'
        : 'border border-border bg-secondary text-secondary-foreground dark:border-border dark:bg-secondary/40 dark:text-foreground dark:ring-1 dark:ring-border/80'
    )}
  >
    {#if showToolsUi}
      <AgentToolStack tools={toolCalls} />
    {/if}
    {#if textBody}
      <div class="flex min-w-0 items-start gap-2">
        <p class="min-w-0 whitespace-pre-wrap break-words font-sans text-sm">
          {textBody}
        </p>
        {#if !isUser && !audioItem && agentVoiceGeneratingMessageId === message.id}
          <Volume2
            size={15}
            class="mt-0.5 shrink-0 animate-pulse opacity-75 [animation-duration:1800ms]"
            aria-label="Voice reply is being generated"
          />
        {/if}
      </div>
    {:else if !audioItem}
      <p class="whitespace-pre-wrap break-words font-sans text-sm opacity-80">No text body</p>
    {/if}
    {#if audioItem && selectedChannelId}
      <ChatMessageAttachmentAudio
        channelId={Number(selectedChannelId)}
        externalMessageId={message.id}
        audioItem={audioItem}
      />
    {/if}
    {#if showTokensUi || message.created_at}
      <!-- Stack telemetry + timestamp on their own lines so the stats
           never wrap awkwardly inside narrow bubbles (e.g. the overlay). -->
      <div class={cn('flex min-w-0 flex-col gap-0.5 pt-0.5', isUser ? 'items-end' : 'items-start')}>
        {#if showTokensUi}
          <AgentTokenCounter
            inputValue={inputTokensIncl}
            outputValue={outputTokens}
            {costLabel}
            {elapsedLabel}
            animate={tokenCountAnimates}
            tooltip={tokenTooltip}
            className={isUser ? 'text-amber-100' : 'text-emerald-700 dark:text-emerald-300'}
            costClassName={isUser
              ? 'font-semibold text-cyan-200'
              : 'font-semibold text-violet-600 dark:text-violet-400'}
          />
        {/if}
        {#if message.created_at}
          <span
            class={cn(
              'shrink-0 tabular-nums font-sans text-[10px] leading-none opacity-40',
              isUser ? 'opacity-50' : 'self-end'
            )}
          >
            {formatChatTimestamp(message.created_at)}
          </span>
        {/if}
      </div>
    {/if}
  </div>
</div>
