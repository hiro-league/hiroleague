<script lang="ts">
  /** People → Roles (Phase 9a): name a new role; its rights are given after, in its own tab. */
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$lib/components/ui/dialog';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { Input } from '$lib/components/ui/input';
  import type { RolesController } from '../state/roles-controller.svelte';

  let { ctrl }: { ctrl: RolesController } = $props();

  function submit(event: SubmitEvent) {
    event.preventDefault();
    void ctrl.submitNew();
  }
</script>

<Dialog.Root
  open={ctrl.newName !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.newName = null;
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>New role</Dialog.Title>
    </Dialog.Header>
    <form id="new-role-form" class="grid gap-4" onsubmit={submit}>
      <p class="text-sm text-muted-foreground">It starts with no rights anywhere; give it what it needs in its tab.</p>
      <FormField label="Name">
        <Input
          value={ctrl.newName ?? ''}
          oninput={(e) => (ctrl.newName = e.currentTarget.value)}
          placeholder="Guest, Nanny, Teen"
          autocomplete="off"
          required
        />
      </FormField>
    </form>
    <Dialog.Footer>
      <Button variant="outline" onclick={() => (ctrl.newName = null)}>Cancel</Button>
      <Button type="submit" form="new-role-form" disabled={ctrl.busy || !(ctrl.newName ?? '').trim()}>Add role</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
