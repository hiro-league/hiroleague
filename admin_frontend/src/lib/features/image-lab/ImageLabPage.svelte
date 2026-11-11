<script lang="ts">
  import { onMount } from 'svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import Notice from '$kit/ui/notice.svelte';
  import Loading from '$kit/ui/loading.svelte';
  import { toast } from '$kit/ui/toast.svelte';
  import ImageLabForm from './ImageLabForm.svelte';
  import ImageLabResult from './ImageLabResult.svelte';
  import SaveRecipeDialog from './SaveRecipeDialog.svelte';
  import { createImageLabController } from './state/image-lab-controller.svelte';

  const ctl = createImageLabController();

  onMount(() => {
    void ctl.load();
  });
</script>

<svelte:head>
  <title>Image Lab - Hiro Admin</title>
</svelte:head>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Image Lab" description="Test text-to-image generation, tune parameters, and promote good setups into reusable recipes." />
  {#if ctl.loading}
    <Loading label="Loading Image Lab…" />
  {:else if ctl.error}
    <Notice message={ctl.error} />
  {:else}
    <div class="grid gap-5 lg:grid-cols-2">
      <ImageLabForm {ctl} />
      <ImageLabResult {ctl} />
    </div>
  {/if}
</section>

<SaveRecipeDialog {ctl} />
