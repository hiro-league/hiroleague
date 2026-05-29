<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS.agent}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.agent}
>
  {#if ctrl.sectionDescription('chat')}
    <p class="text-sm text-muted-foreground">{ctrl.sectionDescription('chat')}</p>
  {/if}

  {#if ctrl.draft}
    <SectionCardMuted
      title="Chat instructions"
      description="General answering guidance injected into the current user turn (ahead of the question), alongside any retrieved knowledge and memories. Authored in Markdown; sent to the model as text."
    >
      <MarkdownEditorPreview
        editorLabel="Instructions markdown editor"
        previewLabel="Preview"
        ariaLabel="Chat answering instructions (markdown)"
        bind:value={ctrl.draft.chat.instructions}
        onInput={ctrl.markDirty}
      />
    </SectionCardMuted>

    <FormField label="Max retained messages" class="max-w-sm">
      <input
        type="number"
        min="1"
        max="100"
        class={ADMIN_SELECT_LG}
        bind:value={ctrl.draft.chat.max_messages}
        oninput={ctrl.markDirty}
      />
      <span class="text-xs text-muted-foreground">
        Conversation history window kept per turn (short-term context for the reply + memory/knowledge retrieval).
      </span>
    </FormField>

    <SectionCardMuted
      title="Citations"
      description="When on, the character cites workspace knowledge inline as [n] and the reply carries the matching source list to clients."
    >
      <label
        class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3"
      >
        <input
          type="checkbox"
          bind:checked={ctrl.draft.chat.cite_sources}
          disabled={ctrl.busy}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Cite knowledge sources in chat replies</span>
      </label>
    </SectionCardMuted>
  {/if}
</div>
