import {
  generateImage,
  getImageLabOptions,
  type ImageLabGenerateResult,
  type ImageLabOptions,
  type ImageProfile
} from '$lib/api/image-lab';
import { patchPreferences } from '$lib/api/preferences';
import type { ToastKind } from '$lib/ui/toast-types';

type Notify = (kind: ToastKind, message: string) => void;

const PROFILE_ID_RE = /^[a-z0-9][a-z0-9_]{1,40}$/;

/**
 * The Lab generates with EXPLICIT params (model/steps/seed + client-composed prompt)
 * against the locked, scaffolding-free playground profile — selecting a recipe only
 * loads its values into the editable form. That keeps the page a transparent
 * what-you-see-is-what-runs surface, and "Save as recipe" promotes the current form
 * into a named `image_profiles` entry via the standard preferences PATCH.
 */
const PLAYGROUND_PROFILE_ID = 'image_playground';

export function createImageLabController() {
  let loading = $state(true);
  let error = $state<string | null>(null);
  let options = $state<ImageLabOptions | null>(null);

  // Editable generation form (recipe values are loaded into these).
  let model = $state('');
  let profileId = $state(PLAYGROUND_PROFILE_ID);
  let prompt = $state('');
  let steps = $state(4);
  let seedText = $state('');
  let stylePrefix = $state('');
  let styleSuffix = $state('');

  let generating = $state(false);
  let generateError = $state<string | null>(null);
  let result = $state<ImageLabGenerateResult | null>(null);

  // Save-as-recipe dialog.
  let saveDialogOpen = $state(false);
  let saveProfileId = $state('');
  let saveProfileLabel = $state('');
  let saving = $state(false);

  const models = $derived(options?.models ?? []);
  const profiles = $derived(options?.profiles ?? ({} as Record<string, ImageProfile>));
  const selectedModel = $derived(models.find((m) => m.id === model) ?? null);
  const modelReady = $derived(selectedModel?.available ?? false);
  const seed = $derived.by(() => {
    const text = seedText.trim();
    if (!text) return null;
    const parsed = Number.parseInt(text, 10);
    return Number.isFinite(parsed) ? parsed : null;
  });
  // Mirrors backend compose_image_prompt (style_prefix, prompt, style_suffix).
  const composedPrompt = $derived(
    [stylePrefix.trim(), prompt.trim(), styleSuffix.trim()].filter(Boolean).join(', ')
  );
  const estimatedCostUsd = $derived.by(() => {
    if (!selectedModel) return null;
    if (selectedModel.per_image === null && selectedModel.per_step === null) return null;
    return (selectedModel.per_image ?? 0) + steps * (selectedModel.per_step ?? 0);
  });

  async function load() {
    loading = true;
    error = null;
    try {
      const payload = await getImageLabOptions();
      options = payload.data;
      const firstAvailable = payload.data.models.find((m) => m.available);
      model = payload.data.default_model ?? firstAvailable?.id ?? payload.data.models[0]?.id ?? '';
      applyProfile(payload.data.default_profile);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load Image Lab options.';
      options = null;
    } finally {
      loading = false;
    }
  }

  /** Load a recipe's values into the editable form (does not generate). */
  function applyProfile(id: string) {
    const profile = profiles[id];
    if (!profile) return;
    profileId = id;
    if (profile.model) model = profile.model;
    steps = profile.steps;
    seedText = profile.seed === null ? '' : String(profile.seed);
    stylePrefix = profile.style_prefix;
    styleSuffix = profile.style_suffix;
  }

  async function generate(notify: Notify) {
    if (!composedPrompt) {
      notify('warning', 'Write a prompt first.');
      return;
    }
    generating = true;
    generateError = null;
    try {
      const payload = await generateImage({
        prompt: composedPrompt,
        profile_id: PLAYGROUND_PROFILE_ID,
        model,
        steps,
        seed
      });
      result = payload.data;
    } catch (err) {
      generateError = err instanceof Error ? err.message : 'Image generation failed.';
    } finally {
      generating = false;
    }
  }

  function openSaveDialog() {
    saveProfileId = '';
    saveProfileLabel = '';
    saveDialogOpen = true;
  }

  function closeSaveDialog() {
    if (saving) return;
    saveDialogOpen = false;
  }

  async function saveProfile(notify: Notify) {
    const id = saveProfileId.trim();
    const label = saveProfileLabel.trim();
    if (!PROFILE_ID_RE.test(id)) {
      notify('warning', 'Recipe id must be a slug: lowercase letters, digits, underscores.');
      return;
    }
    if (profiles[id]?.locked) {
      notify('error', `Recipe "${id}" is locked and cannot be overwritten.`);
      return;
    }
    saving = true;
    try {
      await patchPreferences({
        [`image_profiles.${id}`]: {
          label: label || id,
          locked: false,
          model,
          steps,
          size: null,
          style_prefix: stylePrefix,
          style_suffix: styleSuffix,
          seed
        }
      });
      notify('success', `Saved recipe "${id}".`);
      saveDialogOpen = false;
      await load();
      applyProfile(id);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to save recipe.');
    } finally {
      saving = false;
    }
  }

  async function setDefaultModel(notify: Notify) {
    if (!model) return;
    try {
      await patchPreferences({ 'llm.default_image_gen': model });
      notify('success', `Workspace default image model set to ${model}.`);
      if (options) options = { ...options, default_model: model };
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to set default model.');
    }
  }

  return {
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    get options() {
      return options;
    },
    get models() {
      return models;
    },
    get profiles() {
      return profiles;
    },
    get selectedModel() {
      return selectedModel;
    },
    get modelReady() {
      return modelReady;
    },
    get composedPrompt() {
      return composedPrompt;
    },
    get estimatedCostUsd() {
      return estimatedCostUsd;
    },
    get model() {
      return model;
    },
    set model(value: string) {
      model = value;
    },
    get profileId() {
      return profileId;
    },
    get prompt() {
      return prompt;
    },
    set prompt(value: string) {
      prompt = value;
    },
    get steps() {
      return steps;
    },
    set steps(value: number) {
      steps = value;
    },
    get seedText() {
      return seedText;
    },
    set seedText(value: string) {
      seedText = value;
    },
    get stylePrefix() {
      return stylePrefix;
    },
    set stylePrefix(value: string) {
      stylePrefix = value;
    },
    get styleSuffix() {
      return styleSuffix;
    },
    set styleSuffix(value: string) {
      styleSuffix = value;
    },
    get generating() {
      return generating;
    },
    get generateError() {
      return generateError;
    },
    get result() {
      return result;
    },
    get saveDialogOpen() {
      return saveDialogOpen;
    },
    get saveProfileId() {
      return saveProfileId;
    },
    set saveProfileId(value: string) {
      saveProfileId = value;
    },
    get saveProfileLabel() {
      return saveProfileLabel;
    },
    set saveProfileLabel(value: string) {
      saveProfileLabel = value;
    },
    get saving() {
      return saving;
    },
    load,
    applyProfile,
    generate,
    openSaveDialog,
    closeSaveDialog,
    saveProfile,
    setDefaultModel
  };
}

export type ImageLabController = ReturnType<typeof createImageLabController>;
