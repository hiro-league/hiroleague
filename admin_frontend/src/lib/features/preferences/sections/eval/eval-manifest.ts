/**
 * Declarative manifest for the Eval tab (manifest rollout). Replaces `EvalSection`'s hand-written
 * cards: the eval answer/judge models (model + profile pairs) and the answer-prompt library + judge
 * prompt. The tab's field order derives from this manifest (`EVAL_FIELD_ORDER`).
 */
import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
import {
  manifestFieldPaths,
  type PrefTabManifest
} from '$lib/features/preferences/widgets/manifest/manifest-types';
import { validateRetrievalAgentLimits } from '../graph-engine/retrieval-agent-limits';

export const EVAL_MANIFEST: PrefTabManifest = {
  cards: [
    {
      kind: 'card',
      id: 'evalModels',
      title: 'Evaluation Models',
      description:
        'Models + profiles the eval harness uses — the answer step (memory track) and the judge (both tracks). Eval-only; the knowledge track answers with the production pipeline, not the answer model here.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.evalModels,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [
            {
              kind: 'modelProfile',
              modelKind: 'chat',
              modelPath: 'graph.eval.answer_model',
              profilePath: 'graph.eval.answer_tuning_profile'
            },
            {
              kind: 'modelProfile',
              modelKind: 'chat',
              modelPath: 'graph.eval.judge_model',
              profilePath: 'graph.eval.judge_tuning_profile'
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'evalPrompts',
      title: 'Prompts',
      description: 'Memory-eval answer prompt library and the LLM judge grading prompt. Eval-only.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.evalMemAnswerPrompt,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [
            {
              kind: 'promptLibrary',
              dictPath: 'graph.eval.answer_prompts',
              activeIdPath: 'graph.eval.active_answer_prompt_id',
              heading: 'Mem Eval Answer Prompts',
              headingHelp:
                'A library of named instruction blocks the memory-eval answer step can use (the system prompt is a fixed role). The active profile drives every run. Eval-only; memory track only.',
              hint: 'Drives the memory eval\'s recall leg. Each profile should keep declining with exactly "No information available." when no recalled element supports an answer — the abstain detector recognizes that phrase (and the legacy "I don\'t know"). The locked default carries the structured default (support gates, calibrator examples, absolute-date rules); duplicate it to customize.',
              ariaLabel: 'Mem-eval answer prompt (markdown)',
              editorLabel: 'Answer prompt editor'
            },
            {
              kind: 'prompt',
              path: 'graph.eval.judge_prompt',
              heading: 'Mem Eval Judge Prompt',
              headingHelp:
                'Grading system prompt for the LLM judge that scores answers against the ideal (both tracks). Eval-only.',
              hint: 'Grades each answer against the ideal (both tracks). Blank uses the default: lenient on paraphrase/partial/dates, and recall_sufficient only holds when the judge quotes a real recalled line (verified server-side, so ungrounded "sufficient" claims are dropped). Verdict is always measured against the ideal. Keep the Output Fields section if you customize — on thinking-mode models the judge runs in JSON mode and that section is the only schema the model sees.',
              ariaLabel: 'Eval judge prompt (markdown)',
              editorLabel: 'Eval judge prompt editor'
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'graphEvalModels',
      title: 'Retrieval Agent Model & Prompt',
      description:
        'Model, profile, and system prompt for the agentic memory-retrieval loop the memory eval runs (the Retrieval Agent caps below feed its placeholders). Eval-only; chat has its own under Agent ▸ Agent memory.',
      bodyId: PREFERENCES_SECTION_BODY_IDS.graphEvalModels,
      collapsible: true,
      body: [
        {
          kind: 'grid',
          fields: [
            {
              kind: 'modelProfile',
              modelKind: 'chat',
              modelPath: 'graph.eval.retrieval_model',
              profilePath: 'graph.eval.retrieval_tuning_profile'
            },
            {
              kind: 'promptLibrary',
              dictPath: 'graph.eval.retrieval_agent_prompts',
              activeIdPath: 'graph.eval.active_retrieval_agent_prompt_id',
              hint: "Drives the memory eval's recall leg. Placeholders {MAX_AGENT_TURNS}, {MAX_PARALLEL_SEARCHES}, and {MAX_LIMIT} are filled from the Retrieval Agent caps card at runtime.",
              ariaLabel: 'Mem-eval retrieval agent prompt (markdown)',
              editorLabel: 'Retrieval agent prompt editor'
            }
          ]
        }
      ]
    },
    {
      kind: 'card',
      id: 'graphRetrievalAgent',
      title: 'Retrieval Agent',
      description:
        'Loop-bound caps for the EVAL agentic memory-retrieval path. Chat has its own copy under Agent ▸ Agent memory (split so each surface tunes independently).',
      bodyId: PREFERENCES_SECTION_BODY_IDS.graphRetrievalAgent,
      collapsible: true,
      validate: (d) => validateRetrievalAgentLimits(d.graph.eval.retrieval_agent),
      body: [
        {
          kind: 'panel',
          title: 'Loop limits',
          fields: [
            {
              kind: 'grid',
              fields: [
                { kind: 'number', path: 'graph.eval.retrieval_agent.max_agent_turns' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.max_parallel_searches' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.hops_max' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.limit_default' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.limit_min' },
                { kind: 'number', path: 'graph.eval.retrieval_agent.limit_max' }
              ]
            }
          ]
        },
        {
          kind: 'panel',
          title: 'Answer context',
          hint: 'Caps the recalled set handed to the answerer + judge — score-ranked top-N per kind, each element sanitized to one capped line.',
          fields: [
            {
              kind: 'grid',
              fields: [
                { kind: 'number', path: 'graph.eval.max_elements_per_kind' },
                { kind: 'number', path: 'graph.eval.max_fact_chars' },
                { kind: 'number', path: 'graph.eval.max_episode_chars' },
                { kind: 'number', path: 'graph.eval.max_summary_chars' }
              ]
            }
          ]
        }
      ]
    }
  ]
};

/** Eval-tab field order, derived from the manifest — spread into `PREFERENCE_FIELD_ORDER`. */
export const EVAL_FIELD_ORDER: readonly string[] = manifestFieldPaths(EVAL_MANIFEST);
