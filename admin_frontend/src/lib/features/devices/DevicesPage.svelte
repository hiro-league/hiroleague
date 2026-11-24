<script lang="ts">
  import { onMount } from 'svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import { toast } from '$kit/ui/toast.svelte';
  import { createDevicesController } from './state/devices-controller.svelte';
  import DevicesList from './view/DevicesList.svelte';
  import { DeviceOwnersMock } from './state/device-owners-mock.svelte';

  // The family's paired phones. The channels they chat through are on the Extensions page.
  const ctrl = createDevicesController(toast.show);
  // mockup: Permissions phase 3, whose each device is
  const owners = new DeviceOwnersMock(() => ctrl.rows);

  onMount(() => {
    void ctrl.load();
  });
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Devices" description="The family's phones paired with Hiro." />
  <DevicesList {ctrl} {owners} />
</section>
