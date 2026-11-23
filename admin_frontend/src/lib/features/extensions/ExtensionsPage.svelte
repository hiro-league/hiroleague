<script lang="ts">
  import { Download, Link2 } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import { toast } from '$kit/ui/toast.svelte';
  import ExtensionPairingDialog from './dialogs/ExtensionPairingDialog.svelte';
  import InstallChannelDialog from './dialogs/InstallChannelDialog.svelte';
  import { createExtensionsController } from './state/extensions-controller.svelte';
  import ExtensionAbout from './view/ExtensionAbout.svelte';
  import ExtensionsTable from './view/ExtensionsTable.svelte';
  import KindFilter from './view/KindFilter.svelte';
  import ListenAddressCard from './view/ListenAddressCard.svelte';
  import ChannelSettingsPanel from './view/settings/ChannelSettingsPanel.svelte';

  // The one list of everything plugged into the core: its channel plugins and its apps (Unified communication).
  const ctrl = createExtensionsController(toast.show);
  const settingsRow = $derived(ctrl.panel === 'settings' ? ctrl.picked : null);
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <!-- The page's actions and the list's filter sit in the sticky header, so they stay in reach down a long list. -->
  <PageHeader title="Extensions" description="Everything that plugs into Hiro: its channels (WhatsApp, phones) and its apps (HomeHiro…).">
    {#snippet actions()}
      <Button variant="outline" onclick={() => ctrl.openInstall()}>
        <Download size={15} /> Install a channel
      </Button>
      <Button disabled={ctrl.busy} onclick={() => void ctrl.generatePairingCode()}>
        <Link2 size={15} /> Add an app
      </Button>
    {/snippet}
    <KindFilter picked={ctrl.kinds} counts={ctrl.counts} onchange={ctrl.setKinds} />
  </PageHeader>
  <!-- grid-cols-1 (minmax(0,1fr)): a wide table scrolls inside its card instead of widening the page on a phone. -->
  <section class="grid grid-cols-1 gap-4">
    <ExtensionsTable {ctrl} />
    <ListenAddressCard {ctrl} />
  </section>
</section>

<ExtensionPairingDialog {ctrl} />
<InstallChannelDialog {ctrl} />
<ExtensionAbout {ctrl} />
{#if settingsRow}
  {#key settingsRow.extension_id}
    <ChannelSettingsPanel name={settingsRow.name} label={settingsRow.label} enabled={settingsRow.enabled === true} notify={toast.show} onclose={() => ctrl.closePanel()} />
  {/key}
{/if}
