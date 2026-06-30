<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import EvalModelsCard from '$lib/features/preferences/sections/eval/EvalModelsCard.svelte';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PromptField from '$lib/features/preferences/widgets/prompts/PromptField.svelte';
  import ActivePromptLibraryField from '$lib/features/preferences/widgets/prompts/ActivePromptLibraryField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS.eval}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.eval}
>
  <p class="text-sm text-muted-foreground">
    Settings for the evaluation harness — the answer and judge models the eval runs use, and the
    memory-eval answer/judge prompt libraries. Eval-only; these don't affect production chat,
    knowledge, or memory.
  </p>

  {#if ctrl.draft}
    <EvalModelsCard {ctrl} />

    <!-- Merged the former "Mem Eval Answer Prompts" + "Mem Eval Judge Prompt" cards into one
         "Prompts" section. Both controls share a single row: one grid column each. -->
    <PrefSectionCard
      title="Prompts"
      description="Memory-eval answer prompt library and the LLM judge grading prompt. Eval-only."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.evalMemAnswerPrompt}
    >
      <PrefFieldGrid>
        <div class="grid gap-2">
          <h4
            class="inline-flex items-center gap-1.5 font-sans text-base font-semibold leading-snug text-foreground"
          >
            Mem Eval Answer Prompts
            <FieldHelp
              text="A library of named instruction blocks the memory-eval answer step can use (the system prompt is a fixed role). The active profile drives every run. Eval-only; memory track only."
            />
          </h4>
          <ActivePromptLibraryField
            {ctrl}
            dictPath="graph.eval.answer_prompts"
            activeIdPath="graph.eval.active_answer_prompt_id"
            hint={'Drives the memory eval\'s recall leg. Each profile should keep declining with exactly "No information available." when no recalled element supports an answer — the abstain detector recognizes that phrase (and the legacy "I don\'t know"). The locked default carries the structured default (support gates, calibrator examples, absolute-date rules); duplicate it to customize.'}
            ariaLabel="Mem-eval answer prompt (markdown)"
            editorLabel="Answer prompt editor"
          />
        </div>

        <div class="grid gap-2">
          <h4
            class="inline-flex items-center gap-1.5 font-sans text-base font-semibold leading-snug text-foreground"
          >
            Mem Eval Judge Prompt
            <FieldHelp
              text="Grading system prompt for the LLM judge that scores answers against the ideal (both tracks). Eval-only."
            />
          </h4>
          <PromptField
            {ctrl}
            path="graph.eval.judge_prompt"
            hint={'Grades each answer against the ideal (both tracks). Blank uses the default: lenient on paraphrase/partial/dates, and recall_sufficient only holds when the judge quotes a real recalled line (verified server-side, so ungrounded "sufficient" claims are dropped). Verdict is always measured against the ideal. Keep the Output Fields section if you customize — on thinking-mode models the judge runs in JSON mode and that section is the only schema the model sees.'}
            ariaLabel="Eval judge prompt (markdown)"
            editorLabel="Eval judge prompt editor"
          />
        </div>
      </PrefFieldGrid>
    </PrefSectionCard>
  {/if}
</div>
