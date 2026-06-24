import { browser } from '$app/environment';
import { base } from '$app/paths';
import type { GatewayRow, WorkspaceRow } from '$lib/api/server';
import { createDegradedDetector } from '$lib/live/degraded.svelte';

export type WorkspaceStatusState = 'stopped' | 'running_disconnected' | 'connected';

export type AdminStatusPayload = {
  workspace: WorkspaceRow | null;
  workspace_status: WorkspaceStatusState;
  workspace_status_label: string;
  workspaces: WorkspaceRow[];
  workspaces_error: string | null;
  gateways: GatewayRow[];
  gateways_error: string | null;
  hosting_workspace_id: string | null;
};

type Listener = (payload: AdminStatusPayload) => void;

function createLiveStatusStore() {
  let payload = $state<AdminStatusPayload | null>(null);
  let connected = $state(false);
  let error = $state<string | null>(null);
  const degrade = createDegradedDetector();
  let source: EventSource | null = null;
  // Remember the last requested workspace + whether the store is "active" so we can drop the
  // connection while the tab is hidden and transparently re-establish it on refocus.
  let activeWorkspace: string | null | undefined;
  let active = false;
  const listeners = new Set<Listener>();

  function isHidden(): boolean {
    return typeof document !== 'undefined' && document.visibilityState === 'hidden';
  }

  function emit(nextPayload: AdminStatusPayload) {
    payload = nextPayload;
    for (const listener of listeners) {
      listener(nextPayload);
    }
  }

  function start(workspaceId?: string | null) {
    if (!browser) return;
    active = true;
    activeWorkspace = workspaceId;
    if (source) return;
    // Don't hold a connection while backgrounded — each open tab also owns the knowledge
    // stream, and at ~3 tabs the per-origin HTTP/1.1 cap is hit, stalling ordinary fetches.
    if (isHidden()) return;
    const query = workspaceId ? `?workspace=${encodeURIComponent(workspaceId)}` : '';
    source = new EventSource(`${base}/api/events/status${query}`);
    source.addEventListener('status', (event) => {
      connected = true;
      error = null;
      degrade.onConnected();
      emit(JSON.parse((event as MessageEvent).data) as AdminStatusPayload);
    });
    source.onerror = () => {
      connected = false;
      error = 'Live status disconnected.';
      degrade.onDisconnected();
    };
  }

  function stop() {
    active = false;
    source?.close();
    source = null;
    connected = false;
    degrade.onReset();
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (isHidden()) {
        // Pause (free the connection) but stay "active" so refocus reconnects automatically.
        source?.close();
        source = null;
        connected = false;
        degrade.onReset();
      } else if (active && !source) {
        start(activeWorkspace);
      }
    });
  }

  function subscribe(listener: Listener) {
    listeners.add(listener);
    if (payload) listener(payload);
    return () => {
      listeners.delete(listener);
    };
  }

  return {
    get payload() {
      return payload;
    },
    get connected() {
      return connected;
    },
    get error() {
      return error;
    },
    get degraded() {
      return degrade.degraded;
    },
    start,
    stop,
    subscribe
  };
}

export const liveStatus = createLiveStatusStore();
