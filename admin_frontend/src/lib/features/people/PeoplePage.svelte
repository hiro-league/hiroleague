<script lang="ts">
  /** People (Phase 6): one family list in the core, read by extensions such as HomeHiro. */
  import { onMount } from 'svelte';
  import { UserPlus } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import PersonDialog from './dialogs/PersonDialog.svelte';
  import SignInDialog from './dialogs/SignInDialog.svelte';
  import { createPeopleController } from './state/people-controller.svelte';
  import PeopleListCard from './view/PeopleListCard.svelte';

  const toasts = createToastNotifier();
  const ctrl = createPeopleController(toasts.notify);

  onMount(() => {
    void ctrl.load();
  });
</script>

<AdminPageHeader
  kicker="Core"
  title="People"
  subtitle="The family: who they are, what Hiro calls them, how to reach them, their role. HomeHiro reads this list."
>
  <section class="grid gap-4">
    <SectionCard class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <p class="font-sans text-sm text-muted-foreground">
        Only people who use the admin get a sign-in, and they can do everything there. What each role may do
        in Home is set in HomeHiro.
      </p>
      <Button disabled={ctrl.busy} onclick={() => ctrl.openAdd()}>
        <UserPlus size={15} /> Add person
      </Button>
    </SectionCard>
    <PeopleListCard {ctrl} />
  </section>
</AdminPageHeader>

<PersonDialog {ctrl} />
<SignInDialog {ctrl} />
<ConfirmDialog
  open={ctrl.removeTarget !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.removeTarget = null;
  }}
  title="Remove {ctrl.removeTarget?.name ?? ''}?"
  message="They leave the family list, and HomeHiro stops knowing them as family."
  confirmLabel="Remove"
  pending={ctrl.busy}
  onConfirm={() => void ctrl.submitRemove()}
/>
<ConfirmDialog
  open={ctrl.removeSignInTarget !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.removeSignInTarget = null;
  }}
  title="Take {ctrl.removeSignInTarget?.name ?? ''}'s sign-in away?"
  message="They are signed out now and can't sign in to the admin again until given a new sign-in."
  confirmLabel="Take it away"
  pending={ctrl.busy}
  onConfirm={() => void ctrl.submitRemoveSignIn()}
/>
<ToastHost toast={toasts.toast} />
