<script lang="ts">
  import { onMount } from 'svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ImageLabForm from './ImageLabForm.svelte';
  import ImageLabResult from './ImageLabResult.svelte';
  import SaveRecipeDialog from './SaveRecipeDialog.svelte';
  import { createImageLabController } from './state/image-lab-controller.svelte';

  const toasts = createToastNotifier();
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
    <InlineLoading label="Loading Image Lab…" />
  {:else if ctl.error}
    <InlineDestructiveAlert message={ctl.error} />
  {:else}
    <div class="grid gap-5 lg:grid-cols-2">
      <ImageLabForm {ctl} {toasts} />
      <ImageLabResult {ctl} />
    </div>
  {/if}
</section>

<SaveRecipeDialog {ctl} {toasts} />
<ToastHost toast={toasts.toast} />
