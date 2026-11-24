<script lang="ts">
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import Field from '$kit/ui/field.svelte';
  import { Input } from '$kit/components/ui/input/index.js';
  import CheckboxField from '$kit/ui/checkbox-field.svelte';
  import type { PeopleController } from '../state/people-controller.svelte';

  let { ctrl }: { ctrl: PeopleController } = $props();
  const uid = $props.id();

  function submit(event: SubmitEvent) {
    event.preventDefault();
    void ctrl.saveForm();
  }
</script>

<Dialog.Root
  open={ctrl.form !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.closeForm();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>{ctrl.editing ? `Edit ${ctrl.editing.name}` : 'Add a person'}</Dialog.Title>
    </Dialog.Header>
    {#if ctrl.form}
      <form id="person-form" class="grid gap-4" onsubmit={submit}>
        <Field label="Name" for="{uid}-name">
          <Input id="{uid}-name" bind:value={ctrl.form.name} required />
        </Field>
        <Field label="What Hiro calls them" for="{uid}-calls" hint="Leave empty to use their name.">
          <Input id="{uid}-calls" bind:value={ctrl.form.calls_them} placeholder={ctrl.form.name} />
        </Field>
        <!-- Permissions phase 1: several roles a person, their rights adding up -->
        <fieldset class="grid gap-1.5">
          <legend class="mb-1.5 font-sans text-sm font-medium">Roles</legend>
          {#each ctrl.roles as role (role.role_id)}
            {@const held = ctrl.form.role_ids.includes(role.role_id)}
            <CheckboxField
              label={role.name}
              checked={held}
              disabled={held && ctrl.form.role_ids.length === 1}
              help={role.says || undefined}
              onchange={() => ctrl.toggleRole(role.role_id, !held)}
            />
          {/each}
          <p class="font-sans text-xs text-muted-foreground">Their rights add up. What each role may do is on Roles.</p>
        </fieldset>
        <Field label="WhatsApp number" for="{uid}-whatsapp" hint="With the country code, e.g. +20 100 123 4567. Empty = none.">
          <Input id="{uid}-whatsapp" bind:value={ctrl.form.whatsapp} inputmode="tel" autocomplete="off" />
        </Field>
        {#if ctrl.formError}
          <p class="text-sm text-destructive" role="alert">{ctrl.formError}</p>
        {/if}
      </form>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" disabled={ctrl.busy} onclick={() => ctrl.closeForm()}>Cancel</Button>
      <Button type="submit" form="person-form" disabled={ctrl.busy || !ctrl.form?.name.trim()}>
        {ctrl.editing ? 'Save' : 'Add'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
