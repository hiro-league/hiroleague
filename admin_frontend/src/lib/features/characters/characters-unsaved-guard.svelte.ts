import { beforeNavigate, goto } from '$app/navigation';

type UnsavedModalMode = 'idle' | 'promise' | 'navigate';

/** In-app discard confirm + SPA navigation interception for Characters edit drafts. */
export function createCharactersUnsavedGuard(
  getDirty: () => boolean,
  getIsEditDetail: () => boolean,
  setDirty: (next: boolean) => void
) {
  let unsavedModalOpen = $state(false);
  let unsavedModalMode = $state<UnsavedModalMode>('idle');
  let unsavedPromiseResolve: ((proceedAfterDiscard: boolean) => void) | null = null;
  let pendingNavigatePath = $state('');

  const leaveGuardActive = $derived.by(() => getDirty() && getIsEditDetail());

  function closeUnsavedModalContinueEditing() {
    unsavedModalOpen = false;
    if (unsavedModalMode === 'promise') {
      unsavedPromiseResolve?.(false);
      unsavedPromiseResolve = null;
    }
    pendingNavigatePath = '';
    unsavedModalMode = 'idle';
  }

  function confirmUnsavedModalDiscard() {
    unsavedModalOpen = false;
    if (unsavedModalMode === 'promise') {
      const r = unsavedPromiseResolve;
      unsavedPromiseResolve = null;
      unsavedModalMode = 'idle';
      r?.(true);
      return;
    }
    if (unsavedModalMode === 'navigate' && pendingNavigatePath) {
      const path = pendingNavigatePath;
      pendingNavigatePath = '';
      unsavedModalMode = 'idle';
      setDirty(false);
      void goto(path, { replaceState: true, noScroll: true, keepFocus: true });
      return;
    }
    pendingNavigatePath = '';
    unsavedModalMode = 'idle';
  }

  async function confirmDiscard(): Promise<boolean> {
    if (!getDirty()) return true;
    unsavedModalMode = 'promise';
    unsavedModalOpen = true;
    return await new Promise<boolean>((resolve) => {
      unsavedPromiseResolve = resolve;
    });
  }

  beforeNavigate(({ cancel, to }) => {
    if (!(getDirty() && getIsEditDetail())) return;
    cancel();
    if (!to?.url) {
      return;
    }
    unsavedModalMode = 'navigate';
    pendingNavigatePath = `${to.url.pathname}${to.url.search}${to.url.hash}`;
    unsavedModalOpen = true;
  });

  $effect(() => {
    if (!leaveGuardActive) return;
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = '';
    }
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  });

  return {
    get unsavedModalOpen(): boolean {
      return unsavedModalOpen;
    },
    closeUnsavedModalContinueEditing,
    confirmUnsavedModalDiscard,
    confirmDiscard
  };
}
