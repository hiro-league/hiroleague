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
    }
  ]
};

/** Eval-tab field order, derived from the manifest — spread into `PREFERENCE_FIELD_ORDER`. */
export const EVAL_FIELD_ORDER: readonly string[] = manifestFieldPaths(EVAL_MANIFEST);
