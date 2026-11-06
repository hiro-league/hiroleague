<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import ExtensionPairingDialog from './dialogs/ExtensionPairingDialog.svelte';
  import ExtensionRemoveDialog from './dialogs/ExtensionRemoveDialog.svelte';
  import { createExtensionsController } from './state/extensions-controller.svelte';
  import ExtensionsListCard from './view/ExtensionsListCard.svelte';
  import ListenAddressCard from './view/ListenAddressCard.svelte';

  const toasts = createToastNotifier();
  const ctrl = createExtensionsController(toasts.notify);

  onMount(() => {
    void ctrl.load();
  });
</script>

<AdminPageHeader
  kicker="Core"
  title="Extensions"
  subtitle="Programs that connect to Hiro on their own, such as HomeHiro."
>
  <section class="grid gap-4">
    <ExtensionsListCard {ctrl} />
    <ListenAddressCard {ctrl} />
  </section>
</AdminPageHeader>

<ExtensionPairingDialog {ctrl} />
<ExtensionRemoveDialog {ctrl} />
<ToastHost toast={toasts.toast} />
