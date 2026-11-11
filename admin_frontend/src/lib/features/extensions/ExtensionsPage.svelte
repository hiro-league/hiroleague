<script lang="ts">
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import { toast } from '$kit/ui/toast.svelte';
  import ExtensionPairingDialog from './dialogs/ExtensionPairingDialog.svelte';
  import ExtensionRemoveDialog from './dialogs/ExtensionRemoveDialog.svelte';
  import { createExtensionsController } from './state/extensions-controller.svelte';
  import ExtensionsListCard from './view/ExtensionsListCard.svelte';
  import ListenAddressCard from './view/ListenAddressCard.svelte';

  const ctrl = createExtensionsController(toast.show);
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Extensions" description="Programs that connect to Hiro on their own, such as HomeHiro." />
  <section class="grid gap-4">
    <ExtensionsListCard {ctrl} />
    <ListenAddressCard {ctrl} />
  </section>
</section>

<ExtensionPairingDialog {ctrl} />
<ExtensionRemoveDialog {ctrl} />
