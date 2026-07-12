/**
 * Human-readable explanation for a terminal / needs-action channel state. Generic
 * across channels — the states (logged_out / banned / replaced / error) come from
 * the plugin's channel.status event detail (§5.4).
 */
export type ChannelStatusLike = {
  state?: string;
  detail?: Record<string, unknown>;
} | null;

export function channelStatusMessage(status: ChannelStatusLike): string {
  const detail = (status?.detail ?? {}) as Record<string, unknown>;
  const reason = typeof detail.reason === 'string' && detail.reason ? ` (${detail.reason})` : '';
  switch (status?.state) {
    case 'logged_out':
      return `Unlinked this device${reason}. Scan the code below to re-pair.`;
    case 'banned': {
      const expire = detail.expire ? ` until ${String(detail.expire)}` : '';
      return `The account was temporarily banned${expire}. Wait it out, then re-pair.`;
    }
    case 'replaced':
      return 'Another client took over this session. Re-pair to relink.';
    case 'error': {
      const msg = typeof detail.message === 'string' && detail.message ? `: ${detail.message}` : '';
      return `Connection error${reason}${msg}. Retrying — re-pair if it persists.`;
    }
    default:
      return '';
  }
}

/** States that mean the link is broken and the user must re-pair (not just reconnect). */
export function channelNeedsRepair(state: string | undefined): boolean {
  return ['logged_out', 'banned', 'replaced', 'error'].includes(state ?? '');
}
