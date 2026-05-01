import { browser } from '$app/environment';
import { base } from '$app/paths';
import type { GatewayRow, WorkspaceRow } from '$lib/api/server';

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
  let source: EventSource | null = null;
  const listeners = new Set<Listener>();

  function emit(nextPayload: AdminStatusPayload) {
    payload = nextPayload;
    for (const listener of listeners) {
      listener(nextPayload);
    }
  }

  function start(workspaceId?: string | null) {
    if (!browser || source) return;
    const query = workspaceId ? `?workspace=${encodeURIComponent(workspaceId)}` : '';
    source = new EventSource(`${base}/api/events/status${query}`);
    source.addEventListener('status', (event) => {
      connected = true;
      error = null;
      emit(JSON.parse((event as MessageEvent).data) as AdminStatusPayload);
    });
    source.onerror = () => {
      connected = false;
      error = 'Live status disconnected.';
    };
  }

  function stop() {
    source?.close();
    source = null;
    connected = false;
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
    start,
    stop,
    subscribe
  };
}

export const liveStatus = createLiveStatusStore();
