// An app's Permissions tab (Permissions phase 8): what it asks, what is approved, what waits; the optional switches
// as the owner sets them; Approve (or Save, for an app with nothing waiting) through the core's approve route.
import { approveExtension, getExtensionApproval, type AppApproval } from '$lib/api/extensions';
import { Action } from '$kit/state/action.svelte';
import { Resource } from '$kit/state/resource.svelte';
import { approvedOptional, declinable, groups, networkName } from '../shared/approval-items';
import { MOCK_HELLO_APPROVAL } from '../mockup/installed';

export type ApprovalSheet = ReturnType<typeof createApprovalSheet>;

/**
 * `appId` is the picked app's id ("" for none, or a channel: nothing is read). `changed` runs after a save, so the
 * list's mark and status follow.
 */
export function createApprovalSheet(appId: () => string, changed: () => Promise<void>) {
  const data = new Resource<AppApproval | null>((signal) => {
    const id = appId();
    // mockup (Installing apps, task 6): Hello's mock row has no record in the core; its approval is mock data
    if (id === MOCK_HELLO_APPROVAL.extension_id) return Promise.resolve(MOCK_HELLO_APPROVAL);
    return id ? getExtensionApproval(id, signal) : Promise.resolve(null);
  });
  // The switches as the owner set them; null until one is touched (then the approved ones show)
  let switches = $state<string[] | null>(null);
  let switchesOf = $state('');
  const approval = $derived(data.data && data.data.extension_id === appId() ? data.data : null);
  const touched = $derived(switchesOf === appId() ? switches : null);
  const picked = $derived(touched ?? (approval ? approvedOptional(approval) : []));
  const saving = new Action({ then: changed });

  return {
    get approval() {
      return approval;
    },
    get error() {
      return data.error;
    },
    get groups() {
      return approval ? groups(approval) : null;
    },
    get waits() {
      return !!approval?.waits;
    },
    get pending() {
      return !!approval?.pending;
    },
    get declinable() {
      return !!approval && declinable(approval);
    },
    /** The optional switches differ from what is approved: Save shows for an app with nothing waiting. */
    get dirty() {
      return touched !== null && approval !== null && [...touched].sort().join() !== approvedOptional(approval).sort().join();
    },
    get networkName() {
      return networkName(approval);
    },
    saving,
    isOn: (key: string) => picked.includes(key),
    setSwitch: (key: string, on: boolean) => {
      const next = on ? [...new Set([...picked, key])] : picked.filter((k) => k !== key);
      switches = next;
      switchesOf = appId();
    },
    /** Approve: every required item, the optional ones switched on. */
    approve: () =>
      saving.run(async () => {
        const id = appId();
        if (!id || id === MOCK_HELLO_APPROVAL.extension_id) return; // mockup: nothing reaches the core
        data.set(await approveExtension(id, picked));
        switches = null;
      })
  };
}
