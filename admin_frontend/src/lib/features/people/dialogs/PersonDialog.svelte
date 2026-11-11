<script lang="ts">
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { Input } from '$kit/components/ui/input/index.js';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import type { PeopleController } from '../state/people-controller.svelte';

  let { ctrl }: { ctrl: PeopleController } = $props();

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
        <FormField label="Name">
          <Input bind:value={ctrl.form.name} required />
        </FormField>
        <FormField label="What Hiro calls them" hint="Leave empty to use their name.">
          <Input bind:value={ctrl.form.calls_them} placeholder={ctrl.form.name} />
        </FormField>
        <FormField label="Role" hint="What each role may do in Home is set in HomeHiro.">
          <PickSelect
            class="h-8 w-full text-sm"
            label="Role"
            value={ctrl.form.role_id}
            options={ctrl.roles.map((role) => ({ value: role.role_id, label: role.name }))}
            onchange={(v) => ctrl.form && (ctrl.form.role_id = v)}
          />
        </FormField>
        <FormField label="WhatsApp number" hint="With the country code, e.g. +20 100 123 4567. Empty = none.">
          <Input bind:value={ctrl.form.whatsapp} inputmode="tel" autocomplete="off" />
        </FormField>
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
