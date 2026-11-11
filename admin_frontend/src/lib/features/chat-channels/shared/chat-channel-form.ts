import type { ChatChannelPayload } from '$lib/api/chat-channels';

/** Editable channel fields in the create/edit modal (API shape uses snake_case IDs). */
export type ChatChannelFormFields = {
  name: string;
  characterId: string;
  description: string;
};

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
