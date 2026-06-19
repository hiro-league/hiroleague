import { describe, expect, it } from 'vitest';
import type { GatewayRow, WorkspaceRow } from '$lib/api/server';
import { findGatewayLink } from './dashboard-gateway';

function workspace(p: Partial<WorkspaceRow> & Pick<WorkspaceRow, 'name'>): WorkspaceRow {
  return {
    id: p.name,
    path: '/ws',
    running: false,
    pid: null,
    ws_connected: false,
    last_connected: null,
    is_current: false,
    is_default: false,
    is_configured: true,
    http_port: 8080,
    plugin_port: 8081,
    admin_port: 8082,
    port_slot: 0,
    gateway_url: null,
    autostart_method: null,
    stderr_log_path: '',
    stderr_log_exists: false,
    stderr_log_size: 0,
    stderr_log_mtime: null,
    stderr_log_recent: false, // required (non-optional) on WorkspaceRow; fixture must supply it
    ...p
  };
}

function gateway(p: Partial<GatewayRow> & Pick<GatewayRow, 'name' | 'host' | 'port'>): GatewayRow {
  return {
    running: false,
    pid: null,
    path: '/gw',
    is_default: false,
    autostart_method: null,
    stderr_log_path: '',
    stderr_log_exists: false,
    stderr_log_size: 0,
    stderr_log_mtime: null,
    stderr_log_recent: false,
    ...p
  };
}

describe('findGatewayLink', () => {
  it('returns the first running workspace with a matching running gateway', () => {
    const workspaces = [
      workspace({ name: 'alpha', running: true, gateway_url: 'http://127.0.0.1:18789' }),
      workspace({ name: 'beta', running: true, gateway_url: 'http://127.0.0.1:18790' })
    ];
    const gateways = [
      gateway({ name: 'gw-a', host: 'localhost', port: 18789, running: true }),
      gateway({ name: 'gw-b', host: '127.0.0.1', port: 18790, running: true })
    ];
    expect(findGatewayLink(workspaces, gateways)).toEqual({ workspace: 'alpha', gateway: 'gw-a' });
  });

  it('matches localhost aliases against 127.0.0.1', () => {
    const workspaces = [
      workspace({ name: 'home', running: true, gateway_url: 'http://127.0.0.1:9000' })
    ];
    const gateways = [gateway({ name: 'local-gw', host: 'localhost', port: 9000, running: true })];
    expect(findGatewayLink(workspaces, gateways)).toEqual({ workspace: 'home', gateway: 'local-gw' });
  });

  it('returns null when no running pair matches', () => {
    const workspaces = [workspace({ name: 'idle', running: false, gateway_url: 'http://127.0.0.1:1' })];
    const gateways = [gateway({ name: 'gw', host: '127.0.0.1', port: 1, running: true })];
    expect(findGatewayLink(workspaces, gateways)).toBeNull();
  });

  it('ignores gateways on the wrong port', () => {
    const workspaces = [
      workspace({ name: 'ws', running: true, gateway_url: 'http://127.0.0.1:5000' })
    ];
    const gateways = [gateway({ name: 'gw', host: '127.0.0.1', port: 5001, running: true })];
    expect(findGatewayLink(workspaces, gateways)).toBeNull();
  });
});
