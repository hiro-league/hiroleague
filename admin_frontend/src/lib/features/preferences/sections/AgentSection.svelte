<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
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
      title="Chat Settings"
      description="Conversation window and knowledge citations for chat replies."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.agentChatSettings}
    >
      <FormField label="Your name" class="max-w-sm">
        <input
          type="text"
          maxlength="120"
          placeholder="e.g. Misho"
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.memory.user_name}
          disabled={ctrl.busy}
          oninput={ctrl.markDirty}
        />
        <span class="text-xs text-muted-foreground">
          Anchors your remembered facts to a named person in the memory graph (instead of a generic
          “User”). <strong>Set this once, early.</strong> Changing it later won’t rename existing
          memories — it starts a separate identity and fragments recall. Leave blank to use “User”.
        </span>
      </FormField>

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

      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          bind:checked={ctrl.draft.chat.cite_sources}
          disabled={ctrl.busy}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Cite knowledge sources in chat replies</span>
      </label>

      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          bind:checked={ctrl.draft.chat.tools_enabled}
          disabled={ctrl.busy}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Enable agent tools in chat</span>
      </label>
    </SectionCardMuted>

    <!-- Consolidated here from the removed "Agent Memory" tab — these toggles bound to the same
         memory.* fields that used to be duplicated on both tabs. Recall/remember + top_k are gated
         by the master "Enable agent memory" switch. -->
    <SectionCardMuted
      title="Agent memory"
      description="Long-term conversation memory on the shared Graphiti graph engine — the agent remembers facts from the user's messages and recalls them on later turns. The models, embedder, and graph search it uses live in the Graph Engine tab."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.memoryRetrieval}
    >
      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          bind:checked={ctrl.draft.memory.enabled}
          disabled={ctrl.busy}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Enable agent memory</span>
      </label>

      <label
        class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3 {!ctrl
          .draft.memory.enabled
          ? 'opacity-50'
          : ''}"
      >
        <input
          type="checkbox"
          bind:checked={ctrl.draft.memory.extraction.enabled}
          disabled={ctrl.busy || !ctrl.draft.memory.enabled}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Remember new facts after each reply</span>
      </label>

      <label
        class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3 {!ctrl
          .draft.memory.enabled
          ? 'opacity-50'
          : ''}"
      >
        <input
          type="checkbox"
          bind:checked={ctrl.draft.memory.search.enabled}
          disabled={ctrl.busy || !ctrl.draft.memory.enabled}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Recall memories before each reply</span>
      </label>

      <FormField label="Memories to recall (top K)" class="max-w-xs">
        <input
          type="number"
          min="1"
          max="100"
          step="1"
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.memory.search.top_k}
          disabled={ctrl.busy || !ctrl.draft.memory.enabled}
          oninput={ctrl.markDirty}
        />
      </FormField>
    </SectionCardMuted>

    <SectionCardMuted
      title="Chat instructions"
      description="General answering guidance injected into the current user turn (ahead of the question), alongside any retrieved knowledge and memories. Authored in Markdown; sent to the model as text."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.agentChatInstructions}
    >
      <MarkdownEditorPreview
        editorLabel="Instructions markdown editor"
        previewLabel="Preview"
        ariaLabel="Chat answering instructions (markdown)"
        bind:value={ctrl.draft.chat.instructions}
        onInput={ctrl.markDirty}
      />
    </SectionCardMuted>
  {/if}
</div>
