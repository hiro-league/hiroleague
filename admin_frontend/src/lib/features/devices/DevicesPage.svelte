<script lang="ts">
  import { onMount } from 'svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import { toast } from '$kit/ui/toast.svelte';
  import { createDevicesController } from './state/devices-controller.svelte';
  import DevicesList from './view/DevicesList.svelte';

  // The family's paired phones. The channels they chat through are on the Extensions page.
  const ctrl = createDevicesController(toast.show);

  onMount(() => {
    void ctrl.load();
  });
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Devices" description="The family's phones paired with Hiro." />
  <DevicesList {ctrl} />
</section>
