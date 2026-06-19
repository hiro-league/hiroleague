import {
  createChatChannel,
  updateChatChannel,
  uploadChatChannelPhoto,
  type ChatChannelRow
} from '$lib/api/chat-channels';
import type { CharacterRow } from '$lib/api/characters';
import {
  isChatChannelFormDirty,
  parseChatChannelFormForSave,
  snapshotChatChannelFormBaseline,
  type ChatChannelFormBaseline,
  type ChatChannelFormFields
} from '$lib/features/chat-channels/shared/chat-channel-form';
import { createUnsavedGuard } from '$lib/navigation/unsaved-guard.svelte';
import type { ToastKind } from '$lib/ui/toast-types';

type ChatChannelFormOptions = {
  getCharacters: () => CharacterRow[];
  getChannels: () => ChatChannelRow[];
  /** Shared "channel admin mutation in progress" flag (also gates delete/clear). */
  isBusy: () => boolean;
  setBusy: (busy: boolean) => void;
  notify: (kind: ToastKind, message: string) => void;
  /** Reload channels/messages after a successful create/update. */
  onSaved: () => Promise<void>;
};

/**
 * Create/edit channel form: open/close lifecycle, dirty tracking, the shared
 * unsaved-changes guard, photo staging, and submit (create/update + photo upload).
 * The busy flag stays owned by the parent controller (shared with delete/clear).
 */
export function createChatChannelForm(opts: ChatChannelFormOptions) {
  const { getCharacters, getChannels, isBusy, setBusy, notify, onSaved } = opts;

  let formOpen = $state(false);
  let formMode = $state<'create' | 'edit'>('create');
  let editingChannelId = $state<number | null>(null);
  let formError = $state<string | null>(null);
  let form = $state<ChatChannelFormFields>({ name: '', characterId: '', description: '' });
  let pendingPhotoDataUrl = $state<string | null>(null);
  let formBaseline = $state<ChatChannelFormBaseline | null>(null);

  const channelFormDirty = $derived(
    isChatChannelFormDirty({ formOpen, baseline: formBaseline, form, pendingPhotoDataUrl })
  );

  const unsaved = createUnsavedGuard(
    () => channelFormDirty,
    () => formOpen,
    (next) => {
      if (!next) finalizeChannelForm();
    }
  );

  const formTitle = $derived(
    formMode === 'create' ? 'New conversation channel' : 'Edit conversation channel'
  );

  const modalChannelPhotoSrc = $derived(
    pendingPhotoDataUrl ??
      (formMode === 'edit' && editingChannelId !== null
        ? (getChannels().find((c) => c.id === editingChannelId)?.photo_data_url ?? null)
        : null)
  );

  function openCreate() {
    formMode = 'create';
    editingChannelId = null;
    formError = null;
    pendingPhotoDataUrl = null;
    form = { name: '', characterId: getCharacters()[0]?.id ?? '', description: '' };
    formBaseline = snapshotChatChannelFormBaseline(form, pendingPhotoDataUrl);
    formOpen = true;
  }

  function openEdit(row: ChatChannelRow) {
    formMode = 'edit';
    editingChannelId = row.id;
    formError = null;
    pendingPhotoDataUrl = null;
    form = {
      name: row.name,
      characterId: row.character_id,
      description: row.description ?? ''
    };
    formBaseline = snapshotChatChannelFormBaseline(form, pendingPhotoDataUrl);
    formOpen = true;
  }

  /** Stack shared unsaved guard above editor when closing with a dirty form. */
  function channelFormBeforeClose(_source: 'backdrop' | 'escape' | 'header'): boolean {
    void _source;
    if (!channelFormDirty) return true;
    if (unsaved.unsavedModalOpen) return false;
    void requestChannelFormDiscardConfirm();
    return false;
  }

  async function requestChannelFormDiscardConfirm() {
    if (await unsaved.confirmDiscard()) {
      finalizeChannelForm();
    }
  }

  function finalizeChannelForm() {
    formOpen = false;
    formBaseline = null;
    pendingPhotoDataUrl = null;
  }

  async function cancelChannelFormExplicit() {
    if (isBusy()) return;
    if (channelFormDirty && !(await unsaved.confirmDiscard())) return;
    finalizeChannelForm();
  }

  async function submitForm() {
    const parsed = parseChatChannelFormForSave(form);
    if (!parsed.ok) {
      formError = parsed.error;
      return;
    }
    formError = null;
    const payload = parsed.payload;

    setBusy(true);
    try {
      let channelIdSaved: number;
      if (formMode === 'edit' && editingChannelId !== null) {
        await updateChatChannel(editingChannelId, payload);
        channelIdSaved = editingChannelId;
        notify('success', 'Channel updated.');
      } else {
        const res = await createChatChannel(payload);
        channelIdSaved = res.data.id;
        notify('success', 'Channel created.');
      }
      if (pendingPhotoDataUrl) {
        await uploadChatChannelPhoto(channelIdSaved, pendingPhotoDataUrl);
        pendingPhotoDataUrl = null;
      }
      finalizeChannelForm();
      await onSaved();
    } catch (err) {
      formError = err instanceof Error ? err.message : 'Save failed.';
    } finally {
      setBusy(false);
    }
  }

  return {
    openCreate,
    openEdit,
    channelFormBeforeClose,
    finalizeChannelForm,
    cancelChannelFormExplicit,
    submitForm,

    get unsaved() {
      return unsaved;
    },
    get formOpen(): boolean {
      return formOpen;
    },
    get formTitle(): string {
      return formTitle;
    },
    get formMode(): 'create' | 'edit' {
      return formMode;
    },
    get form(): ChatChannelFormFields {
      return form;
    },
    set form(v: ChatChannelFormFields) {
      form = v;
    },
    get pendingPhotoDataUrl(): string | null {
      return pendingPhotoDataUrl;
    },
    set pendingPhotoDataUrl(v: string | null) {
      pendingPhotoDataUrl = v;
    },
    get modalChannelPhotoSrc(): string | null {
      return modalChannelPhotoSrc;
    },
    get formError(): string | null {
      return formError;
    },
    get channelFormDirty(): boolean {
      return channelFormDirty;
    }
  };
}
