<script lang="ts">
  import { Download, Link2, PackagePlus } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import PageTabs, { type PageTab } from '$kit/ui/page-tabs.svelte';
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
  import MockupBadge from '$kit/ui/mockup-badge.svelte';
  import CommandDialog from './mockup/CommandDialog.svelte';
  import UpgradeDialog from './mockup/UpgradeDialog.svelte';
  import { createInstallsMock } from './mockup/installs-mock.svelte';

  // The one list of everything plugged into the core: its channel plugins and its apps (Unified communication).
  const ctrl = createExtensionsController(toast.show);
  // mockup (Installing apps, task 6): what the core's installs add, on mock data
  const mock = createInstallsMock();
  const settingsRow = $derived(ctrl.panel === 'settings' ? ctrl.picked : null);
  // mockup (Permissions phase 8)
  const VIEWS = $derived<PageTab<'all' | 'approval'>[]>([
    { id: 'all', label: 'All' },
    { id: 'approval', label: 'Needs approval', count: ctrl.waitingCount, countTone: ctrl.waitingCount ? 'primary' : 'neutral' }
  ]);
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <!-- The page's actions and the list's filter sit in the sticky header, so they stay in reach down a long list. -->
  <PageHeader title="Extensions" description="Everything that plugs into Hiro: its channels (WhatsApp, phones) and its apps (HomeHiro…).">
    {#snippet actions()}
      <MockupBadge title="Installed apps: their state, what is left to set, start, stop, upgrade, and the install and remove commands (mock data)" />
      <Button variant="outline" onclick={() => mock.openInstall()}>
        <PackagePlus size={15} /> Install an app
      </Button>
      <Button variant="outline" onclick={() => ctrl.openInstall()}>
        <Download size={15} /> Install a channel
      </Button>
      <Button disabled={ctrl.busy} onclick={() => void ctrl.generatePairingCode()}>
        <Link2 size={15} /> Add an app
      </Button>
    {/snippet}
    <!-- mockup (Permissions phase 8): All, or only the apps that wait for the owner's approval; the kind filter
         belongs to All alone, so the two never combine -->
    {#snippet tabs()}
      <PageTabs tabs={VIEWS} value={ctrl.attention ? 'approval' : 'all'} onchange={(v) => ctrl.setAttention(v === 'approval')} label="Which extensions" />
    {/snippet}
    {#if !ctrl.attention}
      <KindFilter picked={ctrl.kinds} counts={ctrl.counts} onchange={ctrl.setKinds} />
    {/if}
  </PageHeader>
  <!-- grid-cols-1 (minmax(0,1fr)): a wide table scrolls inside its card instead of widening the page on a phone. -->
  <section class="grid grid-cols-1 gap-4">
    <ExtensionsTable {ctrl} {mock} />
    <ListenAddressCard {ctrl} />
  </section>
</section>

<ExtensionPairingDialog {ctrl} />
<InstallChannelDialog {ctrl} />
<ExtensionAbout {ctrl} {mock} />
<UpgradeDialog {mock} titleOf={ctrl.titleOf} />
<CommandDialog {mock} />
{#if settingsRow}
  {#key settingsRow.extension_id}
    <ChannelSettingsPanel name={settingsRow.name} label={settingsRow.label} enabled={settingsRow.enabled === true} notify={toast.show} onclose={() => ctrl.closePanel()} />
  {/key}
{/if}
