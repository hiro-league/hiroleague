import type { ChatChannelPayload } from '$lib/api/chat-channels';

/** Editable channel fields in the create/edit modal (API shape uses snake_case IDs). */
export type ChatChannelFormFields = {
  name: string;
  characterId: string;
  description: string;
};

/** Snapshot when opening the dialog — unsaved-change detection vs current form state. */
export type ChatChannelFormBaseline = {
  name: string;
  characterId: string;
  description: string;
  pendingPhotoDataUrl: string | null;
};

export function snapshotChatChannelFormBaseline(
  form: ChatChannelFormFields,
  pendingPhotoDataUrl: string | null
): ChatChannelFormBaseline {
  return {
    name: form.name,
    characterId: form.characterId,
    description: form.description,
    pendingPhotoDataUrl: pendingPhotoDataUrl ?? null
  };
}

export function isChatChannelFormDirty(args: {
  formOpen: boolean;
  baseline: ChatChannelFormBaseline | null;
  form: ChatChannelFormFields;
  pendingPhotoDataUrl: string | null;
}): boolean {
  const { formOpen, baseline, form, pendingPhotoDataUrl } = args;
  if (!formOpen || !baseline) return false;
  return (
    form.name !== baseline.name ||
    form.characterId !== baseline.characterId ||
    form.description !== baseline.description ||
    (pendingPhotoDataUrl ?? null) !== (baseline.pendingPhotoDataUrl ?? null)
  );
}

export type ParsedChannelFormResult =
  | { ok: true; payload: ChatChannelPayload }
  | { ok: false; error: string };

/** Validates trimmed fields — caller assigns `error` string to UI state. */
export function parseChatChannelFormForSave(form: ChatChannelFormFields): ParsedChannelFormResult {
  const name = form.name.trim();
  const characterId = form.characterId.trim();

  if (!name || !characterId) {
    return { ok: false, error: 'Name and character are required.' };
  }

  return {
    ok: true,
    payload: {
      name,
      character_id: characterId,
      description: form.description.trim()
    }
  };
}
