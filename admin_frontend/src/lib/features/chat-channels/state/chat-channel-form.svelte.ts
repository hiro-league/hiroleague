import {
  createChatChannel,
  updateChatChannel,
  uploadChatChannelPhoto,
  type ChatChannelRow
} from '$lib/api/chat-channels';
import type { CharacterRow } from '$lib/api/characters';
import {
  parseChatChannelFormForSave,
  type ChatChannelFormFields
} from '$lib/features/chat-channels/shared/chat-channel-form';
import { Draft } from '$kit/state/draft.svelte';
import { ask } from '$kit/ui/confirm.svelte';
import type { ToastKind } from '$kit/ui/toast.svelte';

type ChatChannelFormOptions = {
  getCharacters: () => CharacterRow[];
  getChannels: () => ChatChannelRow[];
  notify: (kind: ToastKind, message: string) => void;
  /** Reload channels/messages after a successful create/update. */
  onSaved: () => Promise<void>;
};

/** What the dialog edits: the channel's fields and the photo picked but not yet uploaded. */
type ChannelEdit = { fields: ChatChannelFormFields; photo: string | null };

const blank = (characterId = ''): ChannelEdit => ({
  fields: { name: '', characterId, description: '' },
  photo: null
});

/**
 * Create/edit channel form: open/close lifecycle, the draft (dirty, undo, "leave without saving?"),
 * photo staging, and submit (create/update + photo upload). Its save is the draft's own action; the
 * parent controller adds it to its busy flag (shared with delete/clear).
 */
export function createChatChannelForm(opts: ChatChannelFormOptions) {
  const { getCharacters, getChannels, notify, onSaved } = opts;

  let formOpen = $state(false);
  let formMode = $state<'create' | 'edit'>('create');
  let editingChannelId = $state<number | null>(null);

  async function persist(edit: ChannelEdit) {
    const parsed = parseChatChannelFormForSave(edit.fields);
    if (!parsed.ok) throw new Error(parsed.error);
    let channelIdSaved: number;
    if (formMode === 'edit' && editingChannelId !== null) {
      await updateChatChannel(editingChannelId, parsed.payload);
      channelIdSaved = editingChannelId;
      notify('success', 'Channel updated.');
    } else {
      const res = await createChatChannel(parsed.payload);
      channelIdSaved = res.id;
      notify('success', 'Channel created.');
    }
    if (edit.photo) await uploadChatChannelPhoto(channelIdSaved, edit.photo);
    finalizeChannelForm();
    await onSaved();
  }

  const draft = new Draft<ChannelEdit>(blank(), { save: persist });

  /** Only an open dialog has unsaved changes. */
  const channelFormDirty = $derived(formOpen && draft.dirty);

  const formTitle = $derived(
    formMode === 'create' ? 'New conversation channel' : 'Edit conversation channel'
  );

  const modalChannelPhotoSrc = $derived(
    draft.value.photo ??
      (formMode === 'edit' && editingChannelId !== null
        ? (getChannels().find((c) => c.id === editingChannelId)?.photo_data_url ?? null)
        : null)
  );

  function openCreate() {
    formMode = 'create';
    editingChannelId = null;
    draft.action.clear();
    draft.load(blank(getCharacters()[0]?.id ?? ''), true);
    formOpen = true;
  }

  function openEdit(row: ChatChannelRow) {
    formMode = 'edit';
    editingChannelId = row.id;
    draft.action.clear();
    draft.load(
      {
        fields: {
          name: row.name,
          characterId: row.character_id,
          description: row.description ?? ''
        },
        photo: null
      },
      true
    );
    formOpen = true;
  }

  const discardQuestion = {
    title: 'Discard changes?',
    description: 'You have unsaved edits for this conversation channel. Discard them and close the editor, or keep editing.',
    action: 'Discard',
    danger: true
  };

  /** Ask before the editor closes with changes (the answer closes it, so this one says "not yet"). */
  function channelFormBeforeClose(_source: 'backdrop' | 'escape' | 'header'): boolean {
    void _source;
    if (!channelFormDirty) return true;
    void ask(discardQuestion).then((discard) => {
      if (discard) finalizeChannelForm();
    });
    return false;
  }

  function finalizeChannelForm() {
    formOpen = false;
    draft.undo();
  }

  async function cancelChannelFormExplicit() {
    if (draft.action.busy) return;
    if (channelFormDirty && !(await ask(discardQuestion))) return;
    finalizeChannelForm();
  }

  async function submitForm() {
    await draft.save();
  }

  return {
    openCreate,
    openEdit,
    channelFormBeforeClose,
    finalizeChannelForm,
    cancelChannelFormExplicit,
    submitForm,

    /** The channel form's own save is running. */
    get busy(): boolean {
      return draft.action.busy;
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
      return draft.value.fields;
    },
    set form(v: ChatChannelFormFields) {
      draft.value.fields = v;
    },
    get pendingPhotoDataUrl(): string | null {
      return draft.value.photo;
    },
    set pendingPhotoDataUrl(v: string | null) {
      draft.value.photo = v;
    },
    get modalChannelPhotoSrc(): string | null {
      return modalChannelPhotoSrc;
    },
    get formError(): string | null {
      return draft.action.error || null;
    },
    get channelFormDirty(): boolean {
      return channelFormDirty;
    }
  };
}
