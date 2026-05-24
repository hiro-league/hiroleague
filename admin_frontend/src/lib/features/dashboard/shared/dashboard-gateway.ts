import type { GatewayRow, WorkspaceRow } from '$lib/api/server';

export type GatewayLink = {
  workspace: string;
  gateway: string;
};

function isLocalHost(host: string) {
  return ['0.0.0.0', '127.0.0.1', 'localhost', '::1'].includes(host.toLowerCase());
}

function workspaceGatewayTarget(workspace: WorkspaceRow) {
  if (!workspace.gateway_url) return null;
  try {
    const url = new URL(workspace.gateway_url);
    return { host: url.hostname, port: Number(url.port) };
  } catch {
    return null;
  }
}

function gatewayMatchesWorkspace(gateway: GatewayRow, workspace: WorkspaceRow) {
  const target = workspaceGatewayTarget(workspace);
  if (!target || !target.port || gateway.port !== target.port) return false;
  return gateway.host === target.host || (isLocalHost(gateway.host) && isLocalHost(target.host));
}

export function findGatewayLink(
  workspaceRows: WorkspaceRow[],
  gatewayRows: GatewayRow[]
): GatewayLink | null {
  for (const workspace of workspaceRows.filter((row) => row.running)) {
    const gateway = gatewayRows.find((row) => row.running && gatewayMatchesWorkspace(row, workspace));
    if (gateway) {
      return { workspace: workspace.name, gateway: gateway.name };
    }
  }
  return null;
}
