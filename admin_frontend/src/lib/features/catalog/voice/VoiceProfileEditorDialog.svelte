<script lang="ts">
  /**
   * Voice profile editor (Phase 7b): everything HomeHiro's TTS editor had, shaped like the core's AI
   * profile editor — Name; a Model group with the admin's shared provider → model picker (the catalog's
   * speech models); the Voice (OpenAI's voices, or Gemini's studio voices, voice library and our own
   * voices, each with a sample); the speaking style; speed (OpenAI only, with a reset); and Try it on the
   * right. A profile whose designed voice Google no longer has says so. Designing a voice happens inside
   * the Voice section (My voices), as in HomeHiro. Saved through the preferences API (`voice.profiles`).
   */
  import type { CatalogProviderRow } from '$lib/api/catalog';
  import { Copy, Trash2, TriangleAlert } from '@lucide/svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import FormField from '$lib/components/ui/form-field.svelte';
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import type { VoiceProfileFields, VoiceProfileRow } from '$lib/api/voice';
  import { ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import GeminiVoicePicker from './GeminiVoicePicker.svelte';
  import VoiceTryIt from './VoiceTryIt.svelte';
  import { fieldsOf, type VoiceController } from './voice-controller.svelte';

  let {
    open = $bindable(false),
    profile,
    copyOf = null,
    ctrl,
    catalogProviders,
    activeProviderIds,
    onsaved
  }: {
    open?: boolean;
    profile: VoiceProfileRow | null;
    /** A new profile starting as a copy of this one (Duplicate). */
    copyOf?: VoiceProfileRow | null;
    ctrl: VoiceController;
    catalogProviders: CatalogProviderRow[];
    activeProviderIds: Set<string>;
    onsaved?: (id: string) => void;
  } = $props();

  const NEW: VoiceProfileFields = {
    label: 'New voice profile',
    model: 'google:gemini-3.8-flash-tts',
    voice: 'kore',
    voice_label: 'Kore',
    style: '',
    speed: 1
  };
  let d = $state<VoiceProfileFields>({ ...NEW });
  let base = $state('');
  // The saved profile being edited; null for a new one (or after Duplicate, which saves a new profile).
  let editingId = $state<string | null>(null);
  let saving = $state(false);
  let confirmDelete = $state(false);
  let error = $state<string | null>(null);

  // A fresh draft each time the dialog opens.
  $effect(() => {
    if (!open) return;
    const next: VoiceProfileFields = profile
      ? fieldsOf(profile)
      : copyOf
        ? { ...fieldsOf(copyOf), label: `${copyOf.label} (copy)` }
        : { ...NEW };
    // Built from `next`, not by reading `d` back: reading the draft here made the effect re-run on every edit.
    d = next;
    base = JSON.stringify(next);
    editingId = profile?.id ?? null;
    error = null;
    confirmDelete = false;
  });
  const dirty = $derived(JSON.stringify(d) !== base);
  const isOpenAi = $derived(d.model.startsWith('openai:'));
  const openAiVoices = $derived(ctrl.catalog?.openai_voices ?? []);
  const current = $derived(ctrl.profiles.find((p) => p.id === editingId) ?? null);
  // The saved voice is gone at Google (designed voices expire after a year) and wasn't changed yet.
  const voiceGone = $derived(current?.voice_ok === false && d.voice === current.voice);
  // Hiro's own voice (`voice.hiro_profile`) counts as a use too, as in the list; without it the editor said
  // "Nothing uses this profile yet" for Hiro's voice.
  const usedBy = $derived(
    current ? [...(ctrl.hiroProfile === current.id ? ["Hiro's voice"] : []), ...current.used_by.map(ctrl.useLabel)] : []
  );

  async function save() {
    saving = true;
    const res = await ctrl.save(editingId, { ...d, speed: isOpenAi ? d.speed : 1 });
    saving = false;
    if ('error' in res) {
      error = res.error;
      return;
    }
    open = false;
    onsaved?.(res.id);
  }

  async function remove() {
    if (!current) return;
    saving = true;
    const err = await ctrl.remove(current.id);
    saving = false;
    if (err) {
      error = err;
      return;
    }
    open = false;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-6xl">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2">
        {current ? `Edit ${d.label || 'Untitled'}` : 'New voice profile'}
        {#if !current}<Badge variant="outline">New</Badge>{:else if dirty}<Badge variant="outline">Unsaved</Badge>{/if}
      </Dialog.Title>
      <Dialog.Description>
        {usedBy.length ? `Used by ${usedBy.join(', ')}.` : 'Nothing uses this profile yet.'}
      </Dialog.Description>
    </Dialog.Header>

    <div class="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
      <div class="grid content-start gap-4">
        <FormField label="Name"><input bind:value={d.label} maxlength="80" placeholder="e.g. Door alert" /></FormField>

        <SectionCardMuted title="Model">
          <SingleModelPicker
            embedded
            label="Speech model"
            hint="The model that speaks. Gemini 3.8 Flash TTS: best, 130 languages. Flash-Lite: cheaper, 101 languages."
            selectedId={d.model}
            catalogModels={ctrl.speechModels}
            catalogLoaded={ctrl.speechModelsLoaded}
            catalogAllProviders={catalogProviders}
            workspaceActiveProvidersResolved
            workspaceActiveProviderIds={activeProviderIds}
            busy={false}
            emptyProviders="No speech models in the catalog."
            emptyModelsForProvider="This provider lists no speech models."
            emptyText="No model picked yet."
            clearTitle="Clear the model"
            onSelect={(id) => {
              if (!id) return;
              const toOpenAi = id.startsWith('openai:');
              // A provider change resets the voice to that provider's default (sage / Kore).
              if (toOpenAi !== isOpenAi) {
                d.voice = toOpenAi ? 'sage' : 'kore';
                d.voice_label = toOpenAi ? 'sage' : 'Kore';
              }
              d.model = id;
            }}
          />
        </SectionCardMuted>

        <SectionCardMuted title="Voice">
          <div class="flex items-baseline justify-end">
            <span class="text-xs text-muted-foreground">Using <span class="font-medium text-foreground">{d.voice_label || d.voice}</span></span>
          </div>
          {#if voiceGone}
            <p class="flex items-center gap-1.5 text-sm text-destructive">
              <TriangleAlert size={15} /> Gemini no longer has this voice (designed voices expire after a year). Pick another.
            </p>
          {/if}
          {#if isOpenAi}
            <select
              class={cn(ADMIN_SELECT, 'sm:w-1/2')}
              value={d.voice}
              onchange={(e) => {
                d.voice = e.currentTarget.value;
                d.voice_label = e.currentTarget.value;
              }}
            >
              {#each openAiVoices as v (v)}<option>{v}</option>{/each}
            </select>
          {:else}
            {#key base}
              <GeminiVoicePicker
                value={d.voice}
                designLanguages={ctrl.catalog?.design_languages ?? []}
                onpick={(v) => {
                  d.voice = v.id;
                  d.voice_label = v.label;
                }}
              />
            {/key}
          {/if}
        </SectionCardMuted>

        <FormField label="Speaking style" hint="Tone, pace, accent and emotion, in plain words. It is never read aloud.">
          <textarea rows="3" bind:value={d.style} maxlength="2000" placeholder="e.g. Warm and calm, medium pace, a slight smile in the voice."></textarea>
        </FormField>

        {#if isOpenAi}
          <FormField label="Speed">
            <span class="grid gap-1">
              <span class="flex items-center gap-3">
                <input type="range" min="0.25" max="4" step="0.05" bind:value={d.speed} class="h-1.5 w-full cursor-pointer accent-primary" />
                <span class="w-16 shrink-0 text-right font-mono text-sm tabular-nums">{d.speed.toFixed(2)}×</span>
              </span>
              <span class="flex justify-between pr-[4.75rem] text-xs text-muted-foreground">
                <span>0.25×</span>
                <button type="button" class="underline" onclick={() => (d.speed = 1)}>reset to 1×</button>
                <span>4×</span>
              </span>
            </span>
          </FormField>
        {/if}
      </div>

      <div class="grid content-start self-start lg:sticky lg:top-0">
        <VoiceTryIt editing={{ id: editingId, fields: d, dirty }} profiles={ctrl.profiles} catalog={ctrl.catalog} people={ctrl.people} />
      </div>
    </div>

    {#if error}<InlineDestructiveAlert message={error} />{/if}
    {#if confirmDelete && current}
      <div class="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 px-3 py-2 text-sm">
        <span class="flex-1">
          Delete "{current.label}"?{usedBy.length ? ` ${usedBy.join(', ')} will have no voice until another is picked.` : ''}
        </span>
        <Button size="sm" variant="destructive-outline" disabled={saving} onclick={remove}>Delete</Button>
        <Button size="sm" variant="ghost" onclick={() => (confirmDelete = false)}>Cancel</Button>
      </div>
    {/if}

    <Dialog.Footer class="sm:justify-between">
      <Button variant="destructive-outline" disabled={!current || saving} onclick={() => (confirmDelete = true)}><Trash2 size={13} /> Delete</Button>
      <span class="flex gap-2">
        <Button
          variant="outline"
          disabled={!current}
          onclick={() => {
            // Duplicate: the same settings as a new profile (saved under a new name).
            d = { ...d, label: `${d.label} (copy)` };
            editingId = null;
          }}><Copy size={13} /> Duplicate</Button
        >
        <Button variant="outline" onclick={() => (open = false)}>Cancel</Button>
        <Button onclick={save} disabled={saving || !d.label.trim() || !d.voice.trim() || (!!current && !dirty)}>Save</Button>
      </span>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
