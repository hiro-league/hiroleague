<script lang="ts">
  import { Image as ImageIcon, Save } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import { ADMIN_SECTION_TITLE } from '$lib/styling/admin-tokens';
  import type { ImageLabController } from './state/image-lab-controller.svelte';

  let { ctl }: { ctl: ImageLabController } = $props();

  const dataUri = $derived(
    ctl.result ? `data:${ctl.result.mime_type};base64,${ctl.result.image_base64}` : null
  );
  const downloadName = $derived(
    ctl.result
      ? `image-lab-${ctl.result.model.replace(/[^a-z0-9-]+/gi, '_')}-${ctl.result.seed ?? 'random'}.jpg`
      : 'image-lab.jpg'
  );
</script>

<SectionCard class="grid content-start gap-4">
  <div class="flex items-center justify-between gap-3">
    <h2 class={ADMIN_SECTION_TITLE}>Result</h2>
    {#if ctl.result}
      <div class="flex items-center gap-2">
        <Button size="sm" variant="outline" onclick={() => ctl.openSaveDialog()}>
          <Save size={13} /> Save as recipe
        </Button>
        <a
          class="inline-flex h-8 items-center rounded-md border border-input bg-background px-3 font-sans text-xs font-semibold shadow-xs hover:bg-accent"
          href={dataUri}
          download={downloadName}
        >
          Download
        </a>
      </div>
    {/if}
  </div>

  {#if ctl.generating}
    <InlineLoading label="Generating image…" />
  {:else if ctl.generateError}
    <InlineDestructiveAlert message={ctl.generateError} />
  {:else if ctl.result && dataUri}
    <img
      class="w-full rounded-md border"
      src={dataUri}
      alt={ctl.result.prompt_used}
      width={ctl.result.width ?? undefined}
      height={ctl.result.height ?? undefined}
    />
    <dl class="grid grid-cols-2 gap-x-4 gap-y-1 font-sans text-xs text-muted-foreground sm:grid-cols-3">
      <div><dt class="font-semibold text-foreground">Model</dt><dd>{ctl.result.model}</dd></div>
      <div><dt class="font-semibold text-foreground">Steps</dt><dd>{ctl.result.steps}</dd></div>
      <div><dt class="font-semibold text-foreground">Seed</dt><dd>{ctl.result.seed ?? 'random'}</dd></div>
      <div><dt class="font-semibold text-foreground">Latency</dt><dd>{(ctl.result.elapsed_ms / 1000).toFixed(1)} s</dd></div>
      <div>
        <dt class="font-semibold text-foreground">Est. cost</dt>
        <dd>{ctl.result.estimated_cost_usd === null ? 'n/a' : `$${ctl.result.estimated_cost_usd.toFixed(5)}`}</dd>
      </div>
      <div>
        <dt class="font-semibold text-foreground">Size</dt>
        <dd>{ctl.result.width && ctl.result.height ? `${ctl.result.width}×${ctl.result.height}` : 'unknown'}</dd>
      </div>
    </dl>
    <p class="font-sans text-xs text-muted-foreground">
      <span class="font-semibold text-foreground">Prompt used:</span>
      {ctl.result.prompt_used}
    </p>
  {:else}
    <InlineEmptyState message="No image yet — write a prompt and hit Generate.">
      {#snippet icon()}
        <ImageIcon size={28} />
      {/snippet}
    </InlineEmptyState>
  {/if}
</SectionCard>
