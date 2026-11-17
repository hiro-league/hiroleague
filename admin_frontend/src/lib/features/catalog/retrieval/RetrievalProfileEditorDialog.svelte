<script lang="ts">
  /**
   * The editor of an embedding or a reranker profile, shaped like the voice profile editor with fewer fields: Name;
   * the Model (the settings' provider → model picker, over the catalog's embedding or rerank models and the local
   * ones, with a local model's download under it); and for a local reranker where it runs. An embedder whose data is
   * indexed keeps its model (the server refuses the change too). Saved through the preferences API.
   */
  import { Lock } from '@lucide/svelte';
  import { Action } from '$kit/state/action.svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import { Input } from '$kit/components/ui/input/index.js';
  import Field from '$kit/ui/field.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import Section from '$kit/ui/section.svelte';
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';
  import PrefModelDownload from '$lib/features/preferences/widgets/PrefModelDownload.svelte';
  import { retrieval as ctrl, type RetrievalFields, type RetrievalKind, type RetrievalProfile } from './retrieval-controller.svelte';

  let {
    open = $bindable(false),
    kind,
    profile,
    copyOf = null
  }: { open?: boolean; kind: RetrievalKind; profile: RetrievalProfile | null; copyOf?: RetrievalProfile | null } = $props();

  const uid = $props.id();
  const blank = (): RetrievalFields => ({
    label: kind === 'embedding' ? 'New embedding profile' : 'New reranker profile',
    model: '',
    device: null
  });
  let d = $state<RetrievalFields>(blank());
  const saving = new Action();
  $effect(() => {
    if (!open) return;
    saving.error = '';
    d = profile
      ? { label: profile.label, model: profile.model, device: profile.device ?? null }
      : copyOf
        ? { label: `${copyOf.label} (copy)`, model: copyOf.model, device: copyOf.device ?? null }
        : blank();
  });

  const model = $derived(d.model ? ctrl.model(kind, d.model) : undefined);
  const usedBy = $derived(profile ? ctrl.usedByLine(kind, profile.id) : '');
  const lock = $derived(profile ? ctrl.lockOf(kind, profile.id) : undefined);
  const dirty = $derived(
    !profile || d.label !== profile.label || d.model !== profile.model || (d.device ?? null) !== (profile.device ?? null)
  );

  async function save() {
    await saving.run(async () => {
      await ctrl.save(kind, profile?.id ?? null, { ...d, label: d.label.trim() });
      open = false;
    });
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-2xl">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2">
        {profile ? `Edit ${d.label || 'Untitled'}` : kind === 'embedding' ? 'New embedding profile' : 'New reranker profile'}
        {#if !profile}<Badge variant="outline">New</Badge>{:else if dirty}<Badge variant="outline">Unsaved</Badge>{/if}
      </Dialog.Title>
      <Dialog.Description>
        {usedBy ? `Used by ${usedBy}.` : 'Nothing uses this profile yet.'}
      </Dialog.Description>
    </Dialog.Header>

    <div class="grid content-start gap-4">
      <Field label="Name" for="{uid}-name"><Input id="{uid}-name" bind:value={d.label} maxlength={80} placeholder={kind === 'embedding' ? 'e.g. Memory embedder' : 'e.g. Memory reranker'} /></Field>

      <Section title="Model">
        <!-- The same provider → model picker as the other model settings, over the catalog's models of this kind
             and the local ones. -->
        <SingleModelPicker
          embedded
          label={kind === 'embedding' ? 'Embedding model' : 'Reranking model'}
          hint={kind === 'embedding'
            ? 'Turns text into vectors. Cloud models need the provider’s key; local models must be downloaded first.'
            : 'Orders search results by relevance. Cloud models need the provider’s key; local models must be downloaded first.'}
          selectedId={d.model || null}
          catalogModels={kind === 'embedding' ? ctrl.catalog.embeddingOptions : ctrl.catalog.rerankPickerOptions}
          catalogLoaded={ctrl.catalog.loaded}
          catalogAllProviders={ctrl.catalog.catalogAllProviders}
          workspaceActiveProvidersResolved={ctrl.catalog.activeProvidersStore.resolved}
          workspaceActiveProviderIds={kind === 'embedding'
            ? ctrl.catalog.activeProvidersStore.embeddingActiveProviderIds
            : ctrl.catalog.activeProvidersStore.rerankActiveProviderIds}
          busy={!!lock || saving.busy}
          emptyProviders={kind === 'embedding' ? 'No embedding providers in catalog.' : 'No reranker providers.'}
          emptyModelsForProvider={kind === 'embedding' ? 'No embedding models for this provider.' : 'No reranker models for this provider.'}
          emptyText="No model picked yet."
          clearTitle="Clear the model"
          onSelect={(id) => (d.model = id ?? '')}
        />
        <PrefModelDownload ctrl={ctrl.downloads} kind={kind === 'embedding' ? 'embedder' : 'reranker'} modelId={d.model} />
        {#if lock}
          <p class="flex items-start gap-1.5 text-sm text-muted-foreground"><Lock size={14} class="mt-0.5 shrink-0" /> {lock}</p>
        {/if}
        {#if kind === 'embedding' && model?.dims}
          <p class="text-xs text-muted-foreground">{model.dims} dimensions per vector.</p>
        {/if}
      </Section>

      {#if kind === 'reranker' && model?.local}
        <Section title="Running it here">
          <Field label="Device" hint="Where the model runs on this computer.">
            <PickSelect
              class="h-9 w-full text-sm sm:w-1/2"
              label="Device"
              value={d.device ?? ''}
              options={[
                { value: '', label: 'The best one found' },
                { value: 'cpu', label: 'CPU' },
                { value: 'cuda', label: 'GPU (CUDA)' }
              ]}
              onchange={(v) => (d.device = v || null)}
            />
          </Field>
        </Section>
      {/if}
    </div>

    {#if saving.error}<Notice message={saving.error} />{/if}

    <Dialog.Footer>
      <Button variant="outline" onclick={() => (open = false)}>Cancel</Button>
      <Button onclick={save} disabled={saving.busy || !d.label.trim() || !d.model || !dirty}>Save</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
