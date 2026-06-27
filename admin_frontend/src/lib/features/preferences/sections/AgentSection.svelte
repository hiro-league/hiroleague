<script lang="ts">
  import PromptField from '$lib/features/preferences/widgets/prompts/PromptField.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';
  import PrefTextField from '$lib/features/preferences/widgets/PrefTextField.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';

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
      <PrefFieldGrid>
        <PrefTextField
          {ctrl}
          path="memory.user_name"
          label="Your name"
          maxlength={120}
          placeholder="e.g. Misho"
          disabled={ctrl.busy}
          bind:value={ctrl.draft.memory.user_name}
        />
        <PrefNumberField
          {ctrl}
          path="chat.max_messages"
          label="Max retained messages"
          bind:value={ctrl.draft.chat.max_messages}
        />
      </PrefFieldGrid>
      <span class="text-xs text-muted-foreground">
        Anchors your remembered facts to a named person in the memory graph (instead of a generic
        “User”). <strong>Set this once, early.</strong> Changing it later won’t rename existing
        memories — it starts a separate identity and fragments recall. Leave blank to use “User”.
      </span>

      <PrefFieldGrid>
        <PrefToggleField
          {ctrl}
          path="chat.cite_sources"
          label="Cite knowledge sources in chat replies"
          disabled={ctrl.busy}
          bind:checked={ctrl.draft.chat.cite_sources}
        />
        <PrefToggleField
          {ctrl}
          path="chat.tools_enabled"
          label="Enable agent tools in chat"
          disabled={ctrl.busy}
          bind:checked={ctrl.draft.chat.tools_enabled}
        />
      </PrefFieldGrid>
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
      <PrefToggleField
        {ctrl}
        path="memory.enabled"
        label="Enable agent memory"
        disabled={ctrl.busy}
        bind:checked={ctrl.draft.memory.enabled}
      />

      <PrefFieldGrid>
        <PrefToggleField
          {ctrl}
          path="memory.extraction.enabled"
          label="Remember new facts after each reply"
          disabled={ctrl.busy || !ctrl.draft.memory.enabled}
          class={!ctrl.draft.memory.enabled ? 'opacity-50' : ''}
          bind:checked={ctrl.draft.memory.extraction.enabled}
        />
        <PrefToggleField
          {ctrl}
          path="memory.search.enabled"
          label="Recall memories before each reply"
          disabled={ctrl.busy || !ctrl.draft.memory.enabled}
          class={!ctrl.draft.memory.enabled ? 'opacity-50' : ''}
          bind:checked={ctrl.draft.memory.search.enabled}
        />
        <PrefNumberField
          {ctrl}
          path="memory.search.top_k"
          label="Memories to recall (top K)"
          disabled={ctrl.busy || !ctrl.draft.memory.enabled}
          bind:value={ctrl.draft.memory.search.top_k}
        />
      </PrefFieldGrid>
    </SectionCardMuted>

    <SectionCardMuted
      title="Chat instructions"
      description="General answering guidance injected into the current user turn (ahead of the question), alongside any retrieved knowledge and memories. Authored in Markdown; sent to the model as text."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.agentChatInstructions}
    >
      <PromptField
        {ctrl}
        path="chat.instructions"
        label="Chat instructions"
        ariaLabel="Chat answering instructions (markdown)"
        editorLabel="Instructions markdown editor"
      />
    </SectionCardMuted>
  {/if}
</div>
