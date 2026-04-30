<script lang="ts">
  import { tick } from 'svelte';
  import { onMount } from 'svelte';
  import {
    ArrowLeft,
    Edit3,
    Image as ImageIcon,
    Plus,
    RefreshCw,
    Save,
    Trash2,
    Upload,
    UserRound
  } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import {
    createCharacter,
    deleteCharacter,
    getCharacter,
    listCharacters,
    updateCharacter,
    uploadCharacterPhoto,
    type CharacterDetail,
    type CharacterRow,
    type CharacterSaveBody
  } from '$lib/api/characters';
  import { listCatalogModels, type CatalogModelRow } from '$lib/api/catalog';
  import { createCharactersPreferences } from '$lib/preferences/characters-preferences.svelte';
  import Modal from '$lib/ui/Modal.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { cn } from '$lib/utils';

  type NotifyKind = 'success' | 'error' | 'info' | 'warning';
  type CharacterForm = {
    new_id: string;
    name: string;
    description: string;
    prompt: string;
    backstory: string;
    llm_models: string[];
    voice_models: string[];
    extras_json: string;
    emotions_enabled: boolean;
  };

  const prefs = createCharactersPreferences();

  let toast = $state<{ kind: NotifyKind; message: string } | null>(null);
  let rows = $state<CharacterRow[]>([]);
  let selected = $state<CharacterDetail | null>(null);
  let form = $state<CharacterForm>(emptyForm());
  let loadingList = $state(true);
  let loadingDetail = $state(false);
  let busy = $state(false);
  let listError = $state<string | null>(null);
  let detailError = $state<string | null>(null);
  let dirty = $state(false);
  let catalogReady = $state(false);
  let llmOptions = $state<CatalogModelRow[]>([]);
  let voiceOptions = $state<CatalogModelRow[]>([]);
  let deleteOpen = $state(false);
  let cropOpen = $state(false);
  let cropZoom = $state(1);
  let cropX = $state(0);
  let cropY = $state(0);
  let cropCanvas = $state<HTMLCanvasElement | null>(null);
  let photoInput = $state<HTMLInputElement | null>(null);
  let cropImage: HTMLImageElement | null = null;

  const detailVisible = $derived(prefs.activeTab === 'detail');
  const isNew = $derived(detailVisible && prefs.detailMode === 'edit' && !prefs.characterId);
  const detailTabLabel = $derived(
    isNew ? 'New character' : selected?.name?.trim() || prefs.characterId || 'Detail'
  );

  function emptyForm(): CharacterForm {
    return {
      new_id: '',
      name: '',
      description: '',
      prompt: '',
      backstory: '',
      llm_models: [],
      voice_models: [],
      extras_json: '',
      emotions_enabled: false
    };
  }

  function notify(kind: NotifyKind, message: string) {
    toast = { kind, message };
    window.setTimeout(() => {
      toast = null;
    }, 4500);
  }

  function markDirty() {
    dirty = true;
  }

  function prettyJson(value: unknown) {
    if (value === null || value === undefined) return '';
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }

  function formFromCharacter(character: CharacterDetail): CharacterForm {
    return {
      new_id: character.id,
      name: character.name ?? '',
      description: character.description ?? '',
      prompt: character.prompt ?? '',
      backstory: character.backstory ?? '',
      llm_models: Array.isArray(character.llm_models) ? character.llm_models : [],
      voice_models: Array.isArray(character.voice_models) ? character.voice_models : [],
      extras_json: prettyJson(character.extras),
      emotions_enabled: Boolean(character.emotions_enabled)
    };
  }

  function escapeHtml(value: string) {
    return value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function inlineMarkdown(value: string) {
    return escapeHtml(value)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');
  }

  function markdownHtml(raw: string | null | undefined) {
    const text = (raw ?? '').trim();
    if (!text) return '<p>-</p>';
    return text
      .split(/\n{2,}/)
      .map((block) => {
        const lines = block.split('\n');
        if (lines.every((line) => line.trim().startsWith('- '))) {
          const items = lines
            .map((line) => `<li>${inlineMarkdown(line.trim().slice(2))}</li>`)
            .join('');
          return `<ul>${items}</ul>`;
        }
        const heading = block.match(/^(#{1,3})\s+(.+)$/);
        if (heading) {
          const level = heading[1].length + 2;
          return `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;
        }
        return `<p>${inlineMarkdown(block).replace(/\n/g, '<br>')}</p>`;
      })
      .join('');
  }

  function modelLabel(model: CatalogModelRow) {
    return `${model.display_name} (${model.id})`;
  }

  async function confirmDiscard() {
    return !dirty || window.confirm('Discard unsaved changes?');
  }

  async function loadCharacters() {
    loadingList = true;
    listError = null;
    try {
      const payload = await listCharacters();
      rows = payload.data;
    } catch (err) {
      rows = [];
      listError = err instanceof Error ? err.message : 'Failed to load characters.';
    } finally {
      loadingList = false;
    }
  }

  async function loadCatalogOptions() {
    if (catalogReady) return;
    const [chat, tts, stt] = await Promise.all([
      listCatalogModels({ model_kind: 'chat' }),
      listCatalogModels({ model_kind: 'tts' }),
      listCatalogModels({ model_kind: 'stt' })
    ]);
    llmOptions = chat.data.models;
    const merged = new Map<string, CatalogModelRow>();
    for (const model of [...tts.data.models, ...stt.data.models]) {
      if (!merged.has(model.id)) merged.set(model.id, model);
    }
    voiceOptions = [...merged.values()];
    catalogReady = true;
  }

  async function loadDetail(id: string, mode: 'view' | 'edit') {
    loadingDetail = true;
    detailError = null;
    try {
      if (mode === 'edit') await loadCatalogOptions();
      const payload = await getCharacter(id);
      selected = payload.data;
      if (mode === 'edit') {
        form = formFromCharacter(payload.data);
        dirty = false;
      }
    } catch (err) {
      selected = null;
      detailError = err instanceof Error ? err.message : 'Failed to load character.';
    } finally {
      loadingDetail = false;
    }
  }

  async function openBrowse() {
    if (!(await confirmDiscard())) return;
    selected = null;
    dirty = false;
    await prefs.setState('browse');
    await loadCharacters();
  }

  async function openCharacter(row: CharacterRow) {
    if (!(await confirmDiscard())) return;
    dirty = false;
    await prefs.setState('detail', 'view', row.id);
    await loadDetail(row.id, 'view');
  }

  async function openNewCharacter() {
    if (!(await confirmDiscard())) return;
    await loadCatalogOptions();
    selected = null;
    form = emptyForm();
    dirty = false;
    await prefs.setState('detail', 'edit');
  }

  async function enterEditMode() {
    if (!prefs.characterId) return;
    await prefs.setState('detail', 'edit', prefs.characterId);
    await loadDetail(prefs.characterId, 'edit');
  }

  async function cancelEdit() {
    if (!(await confirmDiscard())) return;
    dirty = false;
    if (prefs.characterId) {
      await prefs.setState('detail', 'view', prefs.characterId);
      await loadDetail(prefs.characterId, 'view');
    } else {
      await openBrowse();
    }
  }

  function validateForm() {
    if (!prefs.characterId && !form.new_id.trim()) return 'Character id is required.';
    if (form.extras_json.trim()) {
      try {
        const parsed = JSON.parse(form.extras_json);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
          return 'Extras must be a JSON object.';
        }
      } catch (err) {
        return err instanceof Error ? `Extras: invalid JSON (${err.message})` : 'Extras: invalid JSON.';
      }
    }
    return null;
  }

  function saveBody(): CharacterSaveBody {
    return {
      character_id: form.new_id.trim() || null,
      name: form.name.trim(),
      description: form.description,
      prompt: prefs.characterId || form.prompt.trim() ? form.prompt : null,
      backstory: form.backstory,
      llm_models_json: form.llm_models.length ? JSON.stringify(form.llm_models) : '',
      voice_models_json: form.voice_models.length ? JSON.stringify(form.voice_models) : '',
      emotions_enabled: form.emotions_enabled,
      extras_json: form.extras_json
    };
  }

  async function saveCharacter() {
    const invalid = validateForm();
    if (invalid) {
      notify('error', invalid);
      return;
    }
    busy = true;
    try {
      const id = prefs.characterId;
      const payload = id ? await updateCharacter(id, saveBody()) : await createCharacter(saveBody());
      for (const warning of payload.data.warnings) notify('warning', warning);
      const savedId = payload.data.character.id;
      notify('success', 'Character saved.');
      dirty = false;
      await prefs.setState('detail', 'edit', savedId);
      await loadCharacters();
      await loadDetail(savedId, 'edit');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Save failed.');
    } finally {
      busy = false;
    }
  }

  async function confirmDelete() {
    if (!prefs.characterId) return;
    busy = true;
    try {
      await deleteCharacter(prefs.characterId);
      notify('success', 'Character deleted.');
      deleteOpen = false;
      await openBrowse();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Delete failed.');
    } finally {
      busy = false;
    }
  }

  async function readFileAsDataUrl(file: File) {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result ?? ''));
      reader.onerror = () => reject(new Error('Failed to read image file.'));
      reader.readAsDataURL(file);
    });
  }

  async function pickPhoto(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    if (!prefs.characterId) {
      notify('warning', 'Save the character before uploading a photo.');
      return;
    }
    const dataUrl = await readFileAsDataUrl(file);
    cropImage = new Image();
    cropImage.onload = async () => {
      cropZoom = 1;
      cropX = 0;
      cropY = 0;
      cropOpen = true;
      await tick();
      renderCropPreview();
    };
    cropImage.src = dataUrl;
  }

  function renderCropPreview() {
    const canvas = cropCanvas;
    const image = cropImage;
    if (!canvas || !image) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    const baseSide = Math.min(image.naturalWidth, image.naturalHeight);
    const side = baseSide / cropZoom;
    const maxX = Math.max(0, image.naturalWidth - side);
    const maxY = Math.max(0, image.naturalHeight - side);
    const sx = Math.min(maxX, Math.max(0, maxX / 2 + (cropX / 100) * (maxX / 2)));
    const sy = Math.min(maxY, Math.max(0, maxY / 2 + (cropY / 100) * (maxY / 2)));

    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, sx, sy, side, side, 0, 0, canvas.width, canvas.height);
  }

  async function submitPhoto() {
    const canvas = cropCanvas;
    if (!canvas || !prefs.characterId) return;
    busy = true;
    try {
      const payload = await uploadCharacterPhoto(prefs.characterId, canvas.toDataURL('image/png'));
      notify('success', `Photo updated (${payload.data}).`);
      cropOpen = false;
      await loadCharacters();
      await loadDetail(prefs.characterId, prefs.detailMode);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      busy = false;
    }
  }

  onMount(async () => {
    prefs.initialize();
    await loadCharacters();
    if (prefs.activeTab === 'detail') {
      if (prefs.characterId) {
        await loadDetail(prefs.characterId, prefs.detailMode);
      } else if (prefs.detailMode === 'edit') {
        await loadCatalogOptions();
        form = emptyForm();
      }
    }
  });
</script>

<section class="grid max-w-[1420px] gap-5">
  <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">Configuration</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Characters</h2>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <div class="inline-flex rounded-lg border bg-card p-1" role="tablist" aria-label="Characters sections">
        <Button
          class={cn(
            'shadow-none',
            prefs.activeTab === 'browse' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
          )}
          variant={prefs.activeTab === 'browse' ? 'secondary' : 'ghost'}
          role="tab"
          aria-selected={prefs.activeTab === 'browse'}
          onclick={openBrowse}
        >
          Browse
        </Button>
        {#if detailVisible}
          <Button variant="secondary" class="max-w-52 truncate shadow-none" role="tab" aria-selected="true">
            <UserRound size={15} /> {detailTabLabel}
          </Button>
        {/if}
      </div>
      <Button onclick={openNewCharacter}><Plus size={16} /> New character</Button>
    </div>
  </div>

  {#if prefs.activeTab === 'browse'}
    <section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="text-lg font-semibold">Browse</h3>
          <span class="font-sans text-sm text-muted-foreground">{rows.length} characters</span>
        </div>
        <Button variant="outline" onclick={loadCharacters}><RefreshCw size={15} /> Refresh</Button>
      </div>

      {#if loadingList}
        <p class="text-muted-foreground">Loading characters...</p>
      {:else if listError}
        <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load characters</strong>
          <span class="block text-sm">{listError}</span>
        </div>
      {:else if rows.length === 0}
        <p class="text-muted-foreground">No characters yet. Create one with the button above.</p>
      {:else}
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {#each rows as row (row.id)}
            <button
              type="button"
              class="grid min-h-32 grid-cols-[64px_minmax(0,1fr)] gap-3 rounded-lg border bg-background/45 p-4 text-left shadow-sm transition hover:border-primary/40 hover:bg-secondary/25"
              onclick={() => openCharacter(row)}
            >
              {#if row.photo_data_url}
                <img
                  class="size-16 rounded-md border object-cover"
                  src={row.photo_data_url}
                  alt=""
                  aria-hidden="true"
                />
              {:else}
                <span class="grid size-16 place-items-center rounded-md border border-dashed bg-muted text-muted-foreground">
                  <UserRound size={24} />
                </span>
              {/if}
              <span class="min-w-0 space-y-1">
                <span class="flex items-center gap-2">
                  <strong class="truncate font-sans text-sm">{row.name || row.id}</strong>
                  {#if row.is_default}
                    <Badge variant="outline">default</Badge>
                  {/if}
                </span>
                <small class="block truncate text-xs text-muted-foreground">{row.id}</small>
                <span class={cn('block text-sm', row.error ? 'text-destructive' : 'text-muted-foreground')}>
                  {row.error || row.description || '-'}
                </span>
              </span>
            </button>
          {/each}
        </div>
      {/if}
    </section>
  {:else if prefs.detailMode === 'view'}
    <section class="grid gap-5 rounded-lg border bg-card p-5 shadow-sm">
      {#if loadingDetail}
        <p class="text-muted-foreground">Loading character...</p>
      {:else if detailError}
        <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load character</strong>
          <span class="block text-sm">{detailError}</span>
        </div>
      {:else if !selected}
        <div class="grid gap-3">
          <h3 class="text-lg font-semibold">No character selected</h3>
          <p class="text-sm text-muted-foreground">Pick a character from Browse or create a new one.</p>
          <div><Button onclick={openBrowse}><ArrowLeft size={15} /> Go to Browse</Button></div>
        </div>
      {:else}
        <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <h3 class="min-w-0 truncate text-2xl font-semibold">{selected.name || selected.id}</h3>
          <div class="flex flex-wrap gap-2">
            <Button onclick={enterEditMode}><Edit3 size={15} /> Edit</Button>
            <Button variant="outline" onclick={openBrowse}><ArrowLeft size={15} /> Back to Browse</Button>
          </div>
        </div>

        <div class="grid gap-6 lg:grid-cols-[208px_minmax(0,1fr)]">
          <div class="grid content-start gap-2">
            {#if selected.photo_data_url}
              <img class="size-48 rounded-md border object-cover" src={selected.photo_data_url} alt="" />
            {:else}
              <div class="grid size-48 place-items-center rounded-md border border-dashed bg-muted text-muted-foreground">
                <UserRound size={54} />
              </div>
            {/if}
            {#if selected.photo_error}
              <p class="max-w-48 text-xs text-destructive">{selected.photo_error}</p>
            {/if}
          </div>
          <div class="grid min-w-0 gap-4">
            <div>
              <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Id</span>
              <p class="font-sans text-sm">{selected.id}</p>
            </div>
            <div>
              <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Description</span>
              <p class="text-sm">{selected.description || '-'}</p>
            </div>
            <div>
              <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Prompt</span>
              <div class="prose-preview mt-1 rounded-md border bg-background/45 p-3 text-sm">
                {@html markdownHtml(selected.prompt)}
              </div>
            </div>
            <div>
              <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Backstory</span>
              <div class="prose-preview mt-1 rounded-md border bg-background/45 p-3 text-sm">
                {@html markdownHtml(selected.backstory)}
              </div>
            </div>
            <div class="grid gap-3 md:grid-cols-2">
              <div>
                <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">LLM models</span>
                <pre class="mt-1 overflow-auto rounded-md border bg-background/45 p-3 text-xs">{prettyJson(selected.llm_models) || '-'}</pre>
              </div>
              <div>
                <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Voice models</span>
                <pre class="mt-1 overflow-auto rounded-md border bg-background/45 p-3 text-xs">{prettyJson(selected.voice_models) || '-'}</pre>
              </div>
            </div>
          </div>
        </div>
      {/if}
    </section>
  {:else}
    <section class="grid gap-5 rounded-lg border bg-card p-5 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <h3 class="text-2xl font-semibold">{prefs.characterId ? `Edit ${prefs.characterId}` : 'New character'}</h3>
        <div class="flex flex-wrap gap-2">
          {#if prefs.characterId && !selected?.is_default}
            <Button variant="destructive" disabled={busy} onclick={() => (deleteOpen = true)}>
              <Trash2 size={15} /> Delete
            </Button>
          {/if}
          <Button variant="outline" disabled={busy} onclick={cancelEdit}>Cancel</Button>
          <Button disabled={busy} onclick={saveCharacter}><Save size={15} /> Save</Button>
        </div>
      </div>

      {#if loadingDetail}
        <p class="text-muted-foreground">Loading character...</p>
      {:else if detailError}
        <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <strong class="font-sans">Could not load character</strong>
          <span class="block text-sm">{detailError}</span>
        </div>
      {/if}

      <div class="grid gap-4">
        {#if !prefs.characterId}
          <label class="field max-w-md">
            Character id
            <input bind:value={form.new_id} oninput={markDirty} />
          </label>
        {/if}

        <label class="field">
          Display name
          <input bind:value={form.name} oninput={markDirty} />
        </label>

        <label class="field">
          Description
          <textarea class="min-h-24" bind:value={form.description} oninput={markDirty}></textarea>
        </label>

        <div class="grid gap-2">
          <span class="field-title">Prompt (markdown)</span>
          <div class="grid gap-4 lg:grid-cols-2">
            <textarea class="markdown-editor" bind:value={form.prompt} oninput={markDirty}></textarea>
            <div class="prose-preview rounded-md border bg-background/45 p-3 text-sm">
              <span class="mb-2 block font-sans text-xs font-semibold uppercase text-muted-foreground">Preview</span>
              {@html markdownHtml(form.prompt)}
            </div>
          </div>
        </div>

        <div class="grid gap-2">
          <span class="field-title">Backstory (markdown)</span>
          <div class="grid gap-4 lg:grid-cols-2">
            <textarea class="markdown-editor" bind:value={form.backstory} oninput={markDirty}></textarea>
            <div class="prose-preview rounded-md border bg-background/45 p-3 text-sm">
              <span class="mb-2 block font-sans text-xs font-semibold uppercase text-muted-foreground">Preview</span>
              {@html markdownHtml(form.backstory)}
            </div>
          </div>
        </div>

        <label class="field">
          LLM models
          <select multiple bind:value={form.llm_models} onchange={markDirty}>
            {#each llmOptions as model (model.id)}
              <option value={model.id}>{modelLabel(model)}</option>
            {/each}
          </select>
        </label>

        <label class="field">
          Voice models (TTS/STT)
          <select multiple bind:value={form.voice_models} onchange={markDirty}>
            {#each voiceOptions as model (model.id)}
              <option value={model.id}>{modelLabel(model)}</option>
            {/each}
          </select>
        </label>

        <label class="field">
          extras (JSON object)
          <textarea class="min-h-28 font-mono" bind:value={form.extras_json} oninput={markDirty}></textarea>
        </label>

        <label class="flex items-center gap-2 font-sans text-sm font-semibold text-muted-foreground">
          <input
            class="size-4"
            type="checkbox"
            bind:checked={form.emotions_enabled}
            onchange={markDirty}
          />
          Emotions enabled (reserved)
        </label>

        {#if prefs.characterId}
          <div class="flex flex-wrap items-center gap-3">
            <input
              class="hidden"
              type="file"
              accept="image/*"
              bind:this={photoInput}
              onchange={pickPhoto}
            />
            <Button variant="outline" onclick={() => photoInput?.click()}>
              <Upload size={15} /> Photo - choose image to crop
            </Button>
            {#if selected?.photo_data_url}
              <img class="size-12 rounded-md border object-cover" src={selected.photo_data_url} alt="" />
            {:else}
              <span class="inline-flex items-center gap-2 text-sm text-muted-foreground">
                <ImageIcon size={15} /> No photo
              </span>
            {/if}
          </div>
        {/if}
      </div>
    </section>
  {/if}
</section>

<ToastHost {toast} />

<Modal
  open={deleteOpen}
  title={`Delete '${prefs.characterId}'?`}
  subtitle="This removes the character folder and index row."
  onClose={() => {
    if (!busy) deleteOpen = false;
  }}
>
  <p class="text-sm text-muted-foreground">This action cannot be undone.</p>
  {#snippet footer()}
    <Button variant="outline" disabled={busy} onclick={() => (deleteOpen = false)}>Cancel</Button>
    <Button variant="destructive" disabled={busy} onclick={confirmDelete}>Delete</Button>
  {/snippet}
</Modal>

<Modal
  open={cropOpen}
  title="Adjust square crop"
  onClose={() => {
    if (!busy) cropOpen = false;
  }}
>
  <div class="grid gap-4">
    <canvas
      class="mx-auto aspect-square w-full max-w-96 rounded-md border bg-muted"
      width="512"
      height="512"
      bind:this={cropCanvas}
    ></canvas>
    <label class="field">
      Zoom
      <input min="1" max="3" step="0.05" type="range" bind:value={cropZoom} oninput={renderCropPreview} />
    </label>
    <div class="grid gap-3 md:grid-cols-2">
      <label class="field">
        Horizontal
        <input min="-100" max="100" step="1" type="range" bind:value={cropX} oninput={renderCropPreview} />
      </label>
      <label class="field">
        Vertical
        <input min="-100" max="100" step="1" type="range" bind:value={cropY} oninput={renderCropPreview} />
      </label>
    </div>
  </div>
  {#snippet footer()}
    <Button variant="outline" disabled={busy} onclick={() => (cropOpen = false)}>Cancel</Button>
    <Button disabled={busy} onclick={submitPhoto}><Upload size={15} /> Upload</Button>
  {/snippet}
</Modal>

<style>
  :global(.field) {
    display: grid;
    gap: 0.375rem;
    font-family: var(--font-title);
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--muted-foreground);
  }

  :global(.field input:not([type='range'])),
  :global(.field textarea),
  :global(.field select) {
    min-height: 2.25rem;
    border-radius: 0.375rem;
    border: 1px solid var(--input);
    background: var(--background);
    color: var(--foreground);
    padding: 0.5rem 0.75rem;
    font-family: var(--font-title);
    font-size: 0.875rem;
    outline: none;
  }

  :global(.field select[multiple]) {
    min-height: 8rem;
  }

  :global(.field textarea.markdown-editor),
  :global(.markdown-editor) {
    min-height: 18rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.875rem;
  }

  :global(.field-title) {
    font-family: var(--font-title);
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--muted-foreground);
  }

  :global(.prose-preview p) {
    margin: 0 0 0.75rem;
  }

  :global(.prose-preview p:last-child),
  :global(.prose-preview ul:last-child) {
    margin-bottom: 0;
  }

  :global(.prose-preview ul) {
    margin: 0 0 0.75rem 1.25rem;
    list-style: disc;
  }

  :global(.prose-preview code) {
    border-radius: 0.25rem;
    background: var(--muted);
    padding: 0.125rem 0.25rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }
</style>
