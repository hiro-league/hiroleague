import type {
  AgentCostSummary,
  AgentMessageMetadata,
  AgentToolCall,
  AgentUsageTotals,
  ChatHistoryMessage
} from '$lib/api/chat-channels';

const INTEGER_FORMAT = new Intl.NumberFormat('en-US');

export function messageAgentMetadata(message: ChatHistoryMessage): AgentMessageMetadata | null {
  return message.metadata?.agent ?? null;
}

export function agentOutputTokens(agent: AgentMessageMetadata | null): number {
  return Math.max(0, Math.trunc(agent?.usage_total?.output_tokens ?? 0));
}

/** Prompt-side tokens for compact UI: billed input + cached prompt tokens. */
export function agentInputTokensIncludingCached(agent: AgentMessageMetadata | null): number {
  const u = agent?.usage_total;
  if (!u) return 0;
  const input = Math.max(0, Math.trunc(u.input_tokens ?? 0));
  const cached = Math.max(0, Math.trunc(u.cached_input_tokens ?? 0));
  return input + cached;
}

/** True while hirocli marks the agent run as in progress (metadata.agent.status === 'processing'). */
export function agentTokensShouldAnimate(agent: AgentMessageMetadata | null): boolean {
  return agent?.status === 'processing';
}

export function agentMetadataByReplyId(
  messages: ChatHistoryMessage[]
): Map<string, AgentMessageMetadata> {
  const out = new Map<string, AgentMessageMetadata>();
  for (const message of messages) {
    if (message.sender_type !== 'user') continue;
    const agent = messageAgentMetadata(message);
    const replyId = agent?.reply_id;
    if (
      replyId &&
      (agentOutputTokens(agent) + agentInputTokensIncludingCached(agent) > 0 ||
        agentCostLabel(agent) ||
        agentElapsedLabel(agent))
    ) {
      out.set(replyId, agent);
    }
  }
  return out;
}

export function formatTokenCount(value: number): string {
  const n = Math.max(0, Math.trunc(value));
  if (n < 10_000) return INTEGER_FORMAT.format(n);
  if (n < 100_000) return `${trimFixed(n / 1_000, 1)}k`;
  if (n < 1_000_000) return `${INTEGER_FORMAT.format(Math.round(n / 1_000))}k`;
  return `${trimFixed(n / 1_000_000, 3)}M`;
}

export function formatTokenInteger(value: number): string {
  return INTEGER_FORMAT.format(Math.max(0, Math.trunc(value)));
}

/**
 * Tiered USD display — matches agent message footer cost (`AgentTokenCounter`).
 * Use for ledger `cost_usd` and any other USD line items in admin.
 */
export function formatUsdCostDisplay(value: number): string {
  return formatMonetaryAmount(value, 'USD');
}

export function agentCostLabel(agent: AgentMessageMetadata | null): string {
  return formatEstimatedCost(agent?.cost);
}

/** Wall-clock duration — same rules as chat message footer (`AgentTokenCounter` elapsed). */
export function formatAgentElapsedMs(value: number | '' | null | undefined): string {
  if (value === '' || value === null || value === undefined) return '';
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '';
  const totalMs = Math.trunc(value);
  if (totalMs < 1000) return `${(totalMs / 1000).toFixed(2)}s`;
  const totalSeconds = Math.round(totalMs / 1000);
  if (totalSeconds < 60) return `${trimFixed(totalMs / 1000, 1)}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}m`;
}

/** Multi-line `title` on token telemetry (usage only; no price — cost stays on the bubble). */
export function agentElapsedLabel(agent: AgentMessageMetadata | null): string {
  return formatAgentElapsedMs(agent?.elapsed_ms);
}

export function telemetryBreakdownTitle(usage: AgentUsageTotals | undefined): string {
  return usageBreakdownTitle(usage);
}

export function usageBreakdownTitle(usage: AgentUsageTotals | undefined): string {
  if (!usage) return '';
  const cached = Math.max(0, Math.trunc(usage.cached_input_tokens ?? 0));
  const input = Math.max(0, Math.trunc(usage.input_tokens ?? 0));
  const totalInput = cached + input;
  const reasoning = Math.max(0, Math.trunc(usage.reasoning_tokens ?? 0));
  const totalOutput = Math.max(0, Math.trunc(usage.output_tokens ?? 0));
  // Provider `output_tokens` includes reasoning; surface non-reasoning completion as Output.
  const outputExReasoning = Math.max(0, totalOutput - reasoning);
  return [
    `Cached: ${formatTokenInteger(cached)}`,
    `Input: ${formatTokenInteger(input)}`,
    `Total Input: ${formatTokenInteger(totalInput)}`,
    `Reasoning: ${formatTokenInteger(reasoning)}`,
    `Output: ${formatTokenInteger(outputExReasoning)}`,
    `Total Output: ${formatTokenInteger(totalOutput)}`
  ].join('\n');
}

export function agentTools(agent: AgentMessageMetadata | null): AgentToolCall[] {
  return agent?.tools ?? [];
}

/** True when an agent metadata blob carries any displayable telemetry (tokens, cost, or elapsed). */
export function hasVisibleAgentTelemetry(agent: AgentMessageMetadata | null): boolean {
  return Boolean(
    agent &&
      (agentOutputTokens(agent) + agentInputTokensIncludingCached(agent) > 0 ||
        agentCostLabel(agent) ||
        agentElapsedLabel(agent))
  );
}

/**
 * Agent metadata to render on a bubble: the message's own metadata, or — for an
 * agent (non-user) reply that lacks it — the inbound user message's metadata keyed
 * by `reply_id` (so telemetry recorded on the request still shows on the reply).
 */
export function resolveAgentMetadata(
  message: ChatHistoryMessage,
  isUser: boolean,
  inboundByReplyId: Map<string, AgentMessageMetadata>
): AgentMessageMetadata | null {
  return messageAgentMetadata(message) ?? (!isUser ? (inboundByReplyId.get(message.id) ?? null) : null);
}

/**
 * Whether to render telemetry on this bubble. Agent replies always show their own;
 * a user message only shows its telemetry when no agent reply already surfaces the
 * same `reply_id` (avoids double-rendering the same stats on both sides).
 */
export function shouldShowAgentTelemetry(
  message: ChatHistoryMessage,
  agent: AgentMessageMetadata | null,
  isUser: boolean,
  messages: ChatHistoryMessage[]
): boolean {
  if (!agent || !hasVisibleAgentTelemetry(agent)) return false;
  if (!isUser) return true;
  const replyId = agent.reply_id;
  return !messages.some(
    (candidate) =>
      candidate.sender_type !== 'user' &&
      candidate.id === replyId &&
      hasVisibleAgentTelemetry(messageAgentMetadata(candidate))
  );
}

function formatMonetaryAmount(value: number, currency: string): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '';
  const symbol = currency === 'USD' ? '$' : `${currency} `;
  if (value >= 1) return `${symbol}${value.toFixed(2)}`;
  if (value >= 0.01) return `${symbol}${value.toFixed(3)}`;
  if (value >= 0.0001) return `${symbol}${value.toFixed(4)}`;
  return `${symbol}${value.toFixed(6)}`;
}

function formatEstimatedCost(cost: AgentCostSummary | undefined): string {
  if (cost?.pricing_available === false) return '';
  const value = cost?.estimated_total;
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '';
  const currency = cost?.currency || 'USD';
  return formatMonetaryAmount(value, currency);
}

function trimFixed(value: number, digits: number): string {
  return value.toFixed(digits).replace(/\.?0+$/, '');
}
