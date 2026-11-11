<script lang="ts">
  /**
   * AI profile editor (dialog): Model, Answer, Budget and Fallback groups on the left, Try it on the
   * right. Inputs bind to `ai.draft`; Save writes `ai.profiles.<id>` through the preferences API.
   */
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$lib/components/ui/dialog';
  import FormField from '$lib/components/ui/form-field.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';
  import AiProfileTryIt from './AiProfileTryIt.svelte';
  import type { AiController } from './ai-controller.svelte';
  import { AT_ONCE_OPTIONS, chainLabel, MAX_FALLBACKS, THINKING_LABELS } from './ai-profile-rules';

  let { ai }: { ai: AiController } = $props();

  const d = $derived(ai.draft);
  const provider = $derived(ai.draftModel.provider);
  const model = $derived(ai.draftModel.model);
  const kind = $derived(provider?.kind ?? 'api');
  const levels = $derived(model?.thinking ?? []);
  const temperatureOff = $derived(!!ai.draftTemperatureNote);
  const fallbackOptions = $derived(ai.profiles.filter((p) => p.id !== d.id));
  const KIND_WORDS = {
    api: 'Paid per question, by the tokens it uses.',
    local: "Free, and nothing leaves the home. The server's PC must be on.",
    plan: 'Counts against your plan, shared with your own use of it.'
  } as const;
</script>

<Dialog.Root
  open={ai.editorOpen}
  onOpenChange={(next) => {
    if (!next) ai.closeEditor();
  }}
>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-5xl">
    <Dialog.Header>
      <Dialog.Title>{ai.editorIsNew ? 'New AI profile' : `Edit ${ai.profileName(d.id) || 'profile'}`}</Dialog.Title>
      <Dialog.Description>
        {ai.usedBy(d.id).length ? `Used by ${ai.usedBy(d.id).join(', ')}.` : 'Nothing uses this profile yet.'}
      </Dialog.Description>
    </Dialog.Header>

    <div class="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <div class="grid content-start gap-4">
        <FormField label="Name">
          <input bind:value={ai.draft.name} placeholder="e.g. Camera questions" />
        </FormField>

        <SectionCardMuted title="Model">
          <!-- The admin's shared single-model picker (provider list → model list). Local servers'
               and plan tools' models are fed to it as catalog-shaped rows by the AI controller. -->
          <SingleModelPicker
            embedded
            label="Model"
            hint="The model this profile asks."
            selectedId={d.model || null}
            catalogModels={ai.pickerModels}
            catalogLoaded={ai.catalogLoaded}
            catalogAllProviders={ai.pickerProviders}
            workspaceActiveProvidersResolved={ai.pickerActiveResolved}
            workspaceActiveProviderIds={ai.pickerActiveIds}
            busy={false}
            emptyProviders="No chat models in the catalog."
            emptyModelsForProvider="This provider lists no chat models."
            emptyText="No model picked yet."
            clearTitle="Clear the model"
            onSelect={(id) => ai.setDraftModel(id)}
          />
          {#if d.model}
            <p class="text-xs text-muted-foreground">{KIND_WORDS[kind]}</p>
          {/if}
          {#if provider?.notReady}
            <p class="text-xs text-amber-700 dark:text-amber-300">{provider.notReady} Its fallback asks meanwhile.</p>
          {/if}
        </SectionCardMuted>

        <SectionCardMuted title="Answer">
          <!-- items-start: a two-line hint in one cell must not stretch the other cells' controls. -->
          <div class="grid items-start gap-3 sm:grid-cols-3">
            <FormField label="Thinking">
              <!-- '' = the model's default (stored as null). -->
              <select
                value={d.thinking ?? ''}
                disabled={!levels.length}
                onchange={(event) => (ai.draft.thinking = (event.currentTarget.value || null) as typeof d.thinking)}
              >
                <option value="">Model default</option>
                {#each levels as level (level)}
                  <option value={level}>{THINKING_LABELS[level]}</option>
                {/each}
              </select>
            </FormField>
            <FormField label="Max tokens" hint="Empty = the model default.">
              <input type="number" min="1" step="64" placeholder="Default" bind:value={ai.draft.maxTokens} />
            </FormField>
            {#if kind === 'local'}
              <FormField label="Context (tokens)" hint="More fits more pictures.">
                <input type="number" min="2048" step="1024" bind:value={ai.draft.context} />
              </FormField>
            {/if}
          </div>
          <FormField
            label="Temperature"
            hint={ai.draftTemperatureNote ?? 'Lower answers the same way each time; higher varies more.'}
          >
            <span class="flex items-center gap-3">
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                class="h-1.5 w-full cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-50"
                value={d.temperature ?? 1}
                disabled={temperatureOff}
                oninput={(event) => (ai.draft.temperature = Number(event.currentTarget.value))}
              />
              <span class="w-16 shrink-0 text-right font-mono text-sm tabular-nums">
                {temperatureOff ? '—' : (d.temperature?.toFixed(1) ?? 'Default')}
              </span>
              {#if !temperatureOff && d.temperature !== null}
                <Button size="sm" variant="ghost" class="shrink-0" onclick={() => (ai.draft.temperature = null)}>
                  Default
                </Button>
              {/if}
            </span>
          </FormField>
          <FormField label="Extra instructions (optional)" hint="Added to every question; leave empty for none.">
            <textarea rows="2" bind:value={ai.draft.instructions} placeholder="e.g. Answer only from what the picture shows."></textarea>
          </FormField>
        </SectionCardMuted>

        <SectionCardMuted title="Budget">
          <div class="grid items-start gap-3 sm:grid-cols-2">
            {#if kind === 'api'}
              <FormField label="Cost per day (USD)" hint="Past it, the fallback asks. Empty = no limit.">
                <input type="number" min="0" step="0.25" bind:value={ai.draft.budget.costPerDay} />
              </FormField>
            {:else}
              <FormField
                label="Questions per hour"
                hint={kind === 'plan'
                  ? "Keeps this profile's share of your plan small. Empty = no limit."
                  : 'Keeps the PC free for you. Empty = no limit.'}
              >
                <input type="number" min="0" step="1" bind:value={ai.draft.budget.perHour} />
              </FormField>
            {/if}
            <FormField label="At once" hint="Questions it works on together; past it they wait their turn.">
              <select bind:value={ai.draft.budget.atOnce}>
                {#each AT_ONCE_OPTIONS as n (n)}
                  <option value={n}>{n}</option>
                {/each}
              </select>
            </FormField>
          </div>
        </SectionCardMuted>

        <SectionCardMuted title="Fallback">
          <FormField
            label="When it can't answer, ask"
            hint="Used when a budget is reached, the provider fails, or the ask must stay local."
          >
            <select
              value={d.fallbackId ?? ''}
              onchange={(event) => (ai.draft.fallbackId = event.currentTarget.value || null)}
            >
              <option value="">Nobody: the ask fails</option>
              {#each fallbackOptions as p (p.id)}
                <option value={p.id}>{p.name}</option>
              {/each}
            </select>
          </FormField>
          {#if d.fallbackId}
            <p class="text-sm">
              <span class="font-semibold">{d.name || 'This profile'}</span>
              <span class="text-muted-foreground">{chainLabel(ai.profiles, ai.draftCheck.chain)}</span>
            </p>
          {/if}
          {#if ai.draftCheck.message}
            <InlineDestructiveAlert message={ai.draftCheck.message} />
          {:else}
            <p class="text-xs text-muted-foreground">At most {MAX_FALLBACKS} fallbacks in a row, and no loops.</p>
          {/if}
        </SectionCardMuted>
      </div>

      <!-- Try it stays in view while the form on the left scrolls. -->
      <div class="grid content-start self-start lg:sticky lg:top-0">
        <AiProfileTryIt {ai} />
      </div>
    </div>

    <Dialog.Footer>
      <Button variant="outline" onclick={() => ai.closeEditor()}>Cancel</Button>
      <Button
        disabled={ai.saving || !d.name.trim() || !d.model || !!ai.draftCheck.message}
        onclick={() => void ai.saveProfile()}
      >
        {ai.saving ? 'Saving…' : 'Save'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
