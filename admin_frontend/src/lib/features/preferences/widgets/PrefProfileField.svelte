<script lang="ts">
  /**
   * Phase 7b step 5: one of Hiro's jobs picks ONE AI profile (`ai_profile_ref` fields: the model, its
   * tuning, limits and fallback in one recipe, kept in Catalog → Profiles), or Hiro's own voice picks a
   * voice profile (`voice_profile_ref`). Replaces the "model picker + tuning profile" pair.
   *
   * The select lists the workspace's profiles from the draft (`ai.profiles` / `voice.profiles`); an AI
   * job can't use a plan tool's model (claude_code:* / codex:*), so those profiles are left out. Under
   * it: the picked profile in one line, or — when none — what the job falls back to (on the draft), and
   * a link to edit it in Catalog → Profiles. No reset dot: the schema default (null) means "not set",
   * not the job's default profile.
   */
  import { ExternalLink } from '@lucide/svelte';
  import Field from '$kit/ui/field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefField } from '$lib/features/preferences/shared/preferences-field.svelte';
  import type { PreferencePath } from '$lib/features/preferences/shared/preferences-schema';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import {
    aiProfileLine,
    hiroJobByPath,
    isPlanModel,
    jobFallbackLine,
    voiceProfileLine,
    type ModelNamer
  } from '$lib/catalog/hiro-jobs';
  import { catalogModelNamer } from '$lib/catalog/model-namer';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** `ai`: an `ai.profiles` id (a job); `voice`: a `voice.profiles` id (Hiro's voice). */
    kind: 'ai' | 'voice';
  };

  let { ctrl, path, kind }: Props = $props();

  const uid = $props.id();
  const field = usePrefField<string | null>(() => ctrl, () => path);
  const job = $derived(kind === 'ai' ? hiroJobByPath(path) : undefined);

  const namer = $derived<ModelNamer>(
    catalogModelNamer([...ctrl.chatOptions, ...ctrl.ttsOptions], ctrl.catalogAllProviders)
  );

  const aiProfiles = $derived(ctrl.draft?.ai?.profiles ?? {});
  const voiceProfiles = $derived(ctrl.draft?.voice?.profiles ?? {});

  /** id → name, sorted by name; AI: plan-tool models left out (the server refuses them for a job). */
  const options = $derived.by(() => {
    const entries =
      kind === 'ai'
        ? Object.entries(aiProfiles)
            .filter(([, p]) => !isPlanModel(p.model))
            .map(([id, p]) => ({ id, name: p.label }))
        : Object.entries(voiceProfiles).map(([id, p]) => ({ id, name: p.label }));
    return entries.sort((a, b) => a.name.localeCompare(b.name));
  });

  const picked = $derived(field.value ?? '');
  // A saved id the list doesn't have (deleted elsewhere): keep it selectable so the box shows it.
  const missing = $derived(picked !== '' && !options.some((o) => o.id === picked));

  const line = $derived.by(() => {
    if (!ctrl.draft) return '';
    if (kind === 'ai') {
      const profile = picked ? aiProfiles[picked] : undefined;
      if (profile) return aiProfileLine(profile, namer);
      if (picked) return `No AI profile "${picked}": pick another.`;
      return job ? jobFallbackLine(ctrl.draft, job.id, namer) : 'Not set.';
    }
    const voice = picked ? voiceProfiles[picked] : undefined;
    if (voice) return voiceProfileLine(voice, namer);
    if (picked) return `No voice profile "${picked}": pick another.`;
    return "Not set: Hiro doesn't speak its replies (a character's own voice profiles still do).";
  });

  const editHref = $derived.by(() => {
    const tab = kind === 'ai' ? 'profiles' : 'voices';
    const known = picked && !missing ? `&edit=${encodeURIComponent(picked)}` : '';
    return `/catalog?tab=${tab}${known}`;
  });


  function onPick(value: string) {
    // '' = not set (null): the job borrows its fallback's profile / Hiro doesn't speak.
    field.value = value || null;
  }
</script>

{#if field.visible}
  <div class="grid gap-1.5">
    <Field label={field.label} for="{uid}-input" help={field.hint} anchor={path}>
      <PickSelect
        id="{uid}-input"
        class="h-8 w-full text-sm"
        label={field.label}
        value={picked}
        options={[
          { value: '', label: kind === 'ai' ? 'Not set' : 'None' },
          ...options.map((option) => ({ value: option.id, label: option.name })),
          ...(missing ? [{ value: picked, label: `${picked} (missing)` }] : [])
        ]}
        onchange={onPick}
      />
    </Field>
    <p class="font-sans text-xs leading-snug text-muted-foreground">{line}</p>
    <a class="inline-flex w-fit items-center gap-1 font-sans text-xs text-primary hover:underline" href={editHref}>
      Edit in Catalog → Profiles <ExternalLink size={11} aria-hidden="true" />
    </a>
  </div>
{/if}
