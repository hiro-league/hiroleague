<script lang="ts">
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import Field from '$kit/ui/field.svelte';
  import { Input } from '$kit/components/ui/input/index.js';
  import type { PeopleController } from '../state/people-controller.svelte';

  let { ctrl }: { ctrl: PeopleController } = $props();
  const uid = $props.id();

  function submit(event: SubmitEvent) {
    event.preventDefault();
    void ctrl.saveSignIn();
  }
</script>

<Dialog.Root
  open={ctrl.signInFor !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.closeSignIn();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>
        {ctrl.signInFor?.has_sign_in ? `${ctrl.signInFor.name}'s sign-in` : `Let ${ctrl.signInFor?.name} sign in`}
      </Dialog.Title>
    </Dialog.Header>
    <form id="sign-in-form" class="grid gap-4" onsubmit={submit}>
      <p class="text-sm text-muted-foreground">
        Whoever signs in to the admin can do everything there. A new password signs them out everywhere.
      </p>
      <Field label="Sign-in name" for="{uid}-name">
        <Input id="{uid}-name" bind:value={ctrl.signInName} autocomplete="off" autocapitalize="none" spellcheck={false} required />
      </Field>
      <Field label="Password" for="{uid}-password" hint="At least 8 characters.">
        <Input id="{uid}-password" bind:value={ctrl.password} type="password" autocomplete="new-password" required />
      </Field>
      <Field label="The password again" for="{uid}-again">
        <Input id="{uid}-again" bind:value={ctrl.passwordAgain} type="password" autocomplete="new-password" required />
      </Field>
      {#if ctrl.signInError}
        <p class="text-sm text-destructive" role="alert">{ctrl.signInError}</p>
      {/if}
    </form>
    <Dialog.Footer class="sm:justify-between">
      {#if ctrl.signInFor?.has_sign_in}
        <Button
          variant="ghost"
          class="text-destructive"
          disabled={ctrl.busy}
          onclick={() => {
            const person = ctrl.signInFor;
            ctrl.closeSignIn();
            ctrl.removeSignInTarget = person;
          }}
        >
          Take the sign-in away
        </Button>
      {:else}
        <span></span>
      {/if}
      <span class="flex gap-2">
        <Button variant="outline" disabled={ctrl.busy} onclick={() => ctrl.closeSignIn()}>Cancel</Button>
        <Button type="submit" form="sign-in-form" disabled={ctrl.busy || !ctrl.signInName.trim() || !ctrl.password}>
          Save
        </Button>
      </span>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
