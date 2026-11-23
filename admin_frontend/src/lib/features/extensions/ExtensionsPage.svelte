<script lang="ts">
  import PageHeader from '$kit/ui/page-header.svelte';
  import SectionLabel from '$kit/ui/section-label.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import { toast } from '$kit/ui/toast.svelte';
  import ExtensionPairingDialog from './dialogs/ExtensionPairingDialog.svelte';
  import ExtensionRemoveDialog from './dialogs/ExtensionRemoveDialog.svelte';
  import { createExtensionsController } from './state/extensions-controller.svelte';
  import ExtensionsListCard from './view/ExtensionsListCard.svelte';
  import ListenAddressCard from './view/ListenAddressCard.svelte';
  // mockup: the one list (Unified communication, phase 2), above today's cards until it is built.
  import { createOneListMockup } from './mockup/one-list-mockup.svelte';
  import OneListMockup from './mockup/OneListMockup.svelte';
  import ExtensionDetailMockup from './mockup/ExtensionDetailMockup.svelte';

  const ctrl = createExtensionsController(toast.show);
  const oneList = createOneListMockup(toast.show);
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Extensions" description="Everything that plugs into Hiro: its channels (WhatsApp, phones) and its apps (HomeHiro…)." />
  <!-- grid-cols-1 (minmax(0,1fr)): a wide table scrolls inside its card instead of widening the page on a phone. -->
  <section class="grid grid-cols-1 gap-4">
    <OneListMockup list={oneList} onAddApp={() => void ctrl.generatePairingCode()} addingApp={ctrl.busy} />
    <SectionLabel class="mt-4">Today's page, until the one list is built</SectionLabel>
    <ExtensionsListCard {ctrl} />
    <ListenAddressCard {ctrl} />
  </section>
</section>

<ExtensionPairingDialog {ctrl} />
<ExtensionRemoveDialog {ctrl} />
<ExtensionDetailMockup list={oneList} />
