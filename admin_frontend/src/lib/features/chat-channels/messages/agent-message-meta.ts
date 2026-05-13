import type {
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

export function agentMetadataByReplyId(
  messages: ChatHistoryMessage[]
): Map<string, AgentMessageMetadata> {
  const out = new Map<string, AgentMessageMetadata>();
  for (const message of messages) {
    if (message.sender_type !== 'user') continue;
    const agent = messageAgentMetadata(message);
    const replyId = agent?.reply_id;
    if (replyId && agentOutputTokens(agent) > 0) {
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

export function usageBreakdownTitle(usage: AgentUsageTotals | undefined): string {
  if (!usage) return '';
  const lines = [
    usageLine('Output', usage.output_tokens),
    usageLine('Input', usage.input_tokens),
    usageLine('Total', usage.total_tokens),
    usageLine('Cached input', usage.cached_input_tokens),
    usageLine('Reasoning', usage.reasoning_tokens)
  ].filter((line): line is string => Boolean(line));
  return lines.join('\n');
}

export function agentTools(agent: AgentMessageMetadata | null): AgentToolCall[] {
  return agent?.tools ?? [];
}

function usageLine(label: string, value: number | undefined): string | null {
  if (typeof value !== 'number') return null;
  return `${label}: ${formatTokenInteger(value)} tokens`;
}

function trimFixed(value: number, digits: number): string {
  return value.toFixed(digits).replace(/\.?0+$/, '');
}
