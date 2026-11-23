<script lang="ts">
  import { Download, Link2 } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import MockupBadge from '$kit/ui/mockup-badge.svelte';
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
  import ExtensionAboutMockup from './mockup/ExtensionAboutMockup.svelte';
  import ExtensionSettingsMockup from './mockup/ExtensionSettingsMockup.svelte';
  import KindFilter from './mockup/KindFilter.svelte';

  const ctrl = createExtensionsController(toast.show);
  const oneList = createOneListMockup(toast.show);
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <!-- The page's actions and the list's filter sit in the sticky header, so they stay in reach down a long list. -->
  <PageHeader title="Extensions" description="Everything that plugs into Hiro: its channels (WhatsApp, phones) and its apps (HomeHiro…).">
    {#snippet adornment()}
      <MockupBadge title="A mockup of the one list: mock rows, and its switches and buttons change nothing" />
    {/snippet}
    {#snippet actions()}
      <Button variant="outline" onclick={() => oneList.notYet('pick a channel to install, from those not installed yet')}>
        <Download size={15} /> Install a channel
      </Button>
      <Button disabled={ctrl.busy} onclick={() => void ctrl.generatePairingCode()}>
        <Link2 size={15} /> Add an app
      </Button>
    {/snippet}
    <KindFilter picked={oneList.kinds} counts={oneList.counts} onchange={oneList.setKinds} />
  </PageHeader>
  <!-- grid-cols-1 (minmax(0,1fr)): a wide table scrolls inside its card instead of widening the page on a phone. -->
  <section class="grid grid-cols-1 gap-4">
    <OneListMockup list={oneList} />
    <ListenAddressCard {ctrl} />
    <SectionLabel class="mt-4">Today's page, until the one list is built</SectionLabel>
    <ExtensionsListCard {ctrl} />
  </section>
</section>

<ExtensionPairingDialog {ctrl} />
<ExtensionRemoveDialog {ctrl} />
<ExtensionAboutMockup list={oneList} />
<ExtensionSettingsMockup list={oneList} />
