import { createActiveProvidersStore } from '$lib/catalog/active-providers/active-providers-store.svelte';
import { listGateways, listWorkspaces, type GatewayRow, type WorkspaceRow } from '$lib/api/server';
import { featureErrorFrom } from '$lib/runtime/feature-errors';
import { activeProviderDisplayNames, activeProviderOverflowCount } from '../shared/dashboard-derive';
import { findGatewayLink, type GatewayLink } from '../shared/dashboard-gateway';

export type DashboardController = ReturnType<typeof createDashboardController>;

export function createDashboardController() {
  const activeProvidersStore = createActiveProvidersStore();

  let workspaces = $state<WorkspaceRow[]>([]);
  let gateways = $state<GatewayRow[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  const activeProviderNames = $derived(activeProviderDisplayNames(activeProvidersStore.rows));

  const activeProviderOverflow = $derived(
    activeProviderOverflowCount(activeProvidersStore.rows.length)
  );

  const runningWorkspaces = $derived(workspaces.filter((workspace) => workspace.running));
  const runningGateways = $derived(gateways.filter((gateway) => gateway.running));
  const runningWorkspaceName = $derived(runningWorkspaces[0]?.name ?? 'None');
  const runningGatewayName = $derived(runningGateways[0]?.name ?? 'None');
  const gatewayLink = $derived(findGatewayLink(workspaces, gateways));

  async function load() {
    loading = true;
    error = null;
    try {
      const [workspacePayload, gatewayPayload] = await Promise.all([
        listWorkspaces(),
        listGateways()
      ]);
      await activeProvidersStore.load({ silent: true });
      workspaces = workspacePayload.data;
      gateways = gatewayPayload.data;
    } catch (err) {
      error = featureErrorFrom(err, 'Unable to load dashboard status.');
      workspaces = [];
      gateways = [];
    } finally {
      loading = false;
    }
  }

  return {
    get activeProvidersStore() {
      return activeProvidersStore;
    },
    get workspaces() {
      return workspaces;
    },
    get gateways() {
      return gateways;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    get activeProviderNames() {
      return activeProviderNames;
    },
    get activeProviderOverflow() {
      return activeProviderOverflow;
    },
    get runningWorkspaces() {
      return runningWorkspaces;
    },
    get runningGateways() {
      return runningGateways;
    },
    get runningWorkspaceName() {
      return runningWorkspaceName;
    },
    get runningGatewayName() {
      return runningGatewayName;
    },
    get gatewayLink() {
      return gatewayLink as GatewayLink | null;
    },
    load
  };
}
