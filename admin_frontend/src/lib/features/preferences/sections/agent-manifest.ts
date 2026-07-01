/**
 * Declarative manifest for the Agent tab (manifest rollout). Replaces `AgentSection`'s two cards:
 * Chat Settings (name / window / citation toggles + chat instructions) and Agent memory (the master
 * enable toggle gating the recall/remember toggles + top-k). The tab's field order derives from this
 * manifest (`AGENT_FIELD_ORDER`).
 *
 * `memory.default_tuning_profile` and `chat.preferred_answering_language` are editable agent-tab
 * schema fields the UI intentionally doesn't surface (see the manifest test's UNEXPOSED set).
 */
import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
import type { WorkspacePreferences } from '$lib/api/preferences';
import {
  manifestFieldPaths,
  type PrefFieldSpec,
  type PrefTabManifest
} from '$lib/features/preferences/widgets/manifest/manifest-types';

const memoryOff = (d: WorkspacePreferences) => !d.memory.enabled;

// Each recall/remember field is its own grid cell, gated by the master "Enable agent memory" switch.
const gatedMemoryField = (field: PrefFieldSpec): PrefFieldSpec => ({
  kind: 'gated',
  disabledWhen: memoryOff,
  fields: [field]
});

export const AGENT_MANIFEST: PrefTabManifest = {
  cards: [
    {
      kind: 'card',
      id: 'agentChatSettings',
      title: 'Chat Settings',
      description: 'Conversation window and knowledge citations for chat replies.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.agentChatSettings,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [
            {
              kind: 'text',
              path: 'memory.user_name',
              maxlength: 120,
              placeholder: 'e.g. Misho',
              hint: 'Anchors your remembered facts to a named person in the memory graph (instead of a generic “User”). Set this once, early. Changing it later won’t rename existing memories — it starts a separate identity and fragments recall. Leave blank to use “User”.'
            },
            { kind: 'number', path: 'chat.max_messages' }
          ]
        },
        // Toggles stacked in the left column so chat instructions fills the right column.
        {
          kind: 'grid',
          fields: [
            {
              kind: 'column',
              fields: [
                { kind: 'toggle', path: 'chat.cite_sources' },
                { kind: 'toggle', path: 'chat.tools_enabled' }
              ]
            },
            {
              kind: 'prompt',
              path: 'chat.instructions',
              hint: 'General answering guidance injected into the current user turn (ahead of the question), alongside any retrieved knowledge and memories. Authored in Markdown; sent to the model as text.',
              ariaLabel: 'Chat answering instructions (markdown)',
              editorLabel: 'Instructions markdown editor'
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'agentMemory',
      title: 'Agent memory',
      description:
        "Long-term conversation memory on the shared Graphiti graph engine — the agent remembers facts from the user's messages and recalls them on later turns. The models, embedder, and graph search it uses live in the Graph Engine tab.",
      bodyId: PREFERENCES_SECTION_BODY_IDS.memoryRetrieval,
      collapsible: true,
      body: [
        { kind: 'toggle', path: 'memory.enabled' },
        {
          kind: 'grid',
          fields: [
            gatedMemoryField({ kind: 'toggle', path: 'memory.extraction.enabled' }),
            gatedMemoryField({ kind: 'toggle', path: 'memory.search.enabled' }),
            gatedMemoryField({ kind: 'number', path: 'memory.search.top_k' })
          ]
        },
        // Windowed batch ingestion knobs (memory.extraction.*) — gated by the memory master switch.
        // How many turns batch into one memory episode and when a batch is closed/flushed.
        {
          kind: 'grid',
          fields: [
            gatedMemoryField({ kind: 'number', path: 'memory.extraction.window_turns' }),
            gatedMemoryField({ kind: 'number', path: 'memory.extraction.session_gap_minutes' }),
            gatedMemoryField({ kind: 'number', path: 'memory.extraction.idle_flush_hours' }),
            gatedMemoryField({ kind: 'number', path: 'memory.extraction.chunk_min_tokens' })
          ]
        },
        // Extraction-time guidance for chat memory (which facts enter the graph from a two-speaker
        // window) — NOT the answer-time chat instructions, and applied to memory only.
        gatedMemoryField({
          kind: 'prompt',
          path: 'memory.extraction.instructions',
          hint: 'Guidance appended to the graph fact-extractor when ingesting chat memory (a two-speaker window of user + assistant turns). By default it tells the extractor to record facts about the user only, using the assistant’s turns as context. This shapes WHICH facts are stored — it is separate from the answer-time chat instructions, and applies to conversation memory only (not knowledge documents).',
          ariaLabel: 'Memory extraction instructions',
          editorLabel: 'Memory extraction instructions editor'
        })
      ]
    }
  ]
};

/** Agent-tab field order, derived from the manifest — spread into `PREFERENCE_FIELD_ORDER`. */
export const AGENT_FIELD_ORDER: readonly string[] = manifestFieldPaths(AGENT_MANIFEST);
