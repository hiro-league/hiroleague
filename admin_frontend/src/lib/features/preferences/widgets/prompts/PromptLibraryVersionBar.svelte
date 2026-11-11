<script lang="ts">
  /**
   * Version picker + New / Duplicate / Delete actions for the prompt-library editor. Extracted from
   * `PromptEditorDialog` so the dialog keeps the editor/preview + seed/dirty logic. The dialog owns the
   * working dict and the mutation handlers; this bar binds the active id and fires the actions.
   */
  import type { AnswerPromptProfile } from '$lib/api/preferences';
  import { Button } from '$kit/components/ui/button/index.js';
  import Field from '$kit/ui/field.svelte';
  import PickSelect from '$kit/ui/pick-select.svelte';

  type Props = {
    /** `[id, profile]` pairs in display order (default first). */
    entries: [string, AnswerPromptProfile][];
    /** The currently-selected profile (non-null; the dialog renders this bar only when it exists). */
    selected: AnswerPromptProfile;
    selectedId: string;
    onCreate: () => void;
    onDuplicate: () => void;
    onDelete: () => void;
  };

  let {
    entries,
    selected,
    selectedId = $bindable(),
    onCreate,
    onDuplicate,
    onDelete
  }: Props = $props();
  const uid = $props.id();
</script>

<div class="flex flex-wrap items-end gap-3">
  <Field label="Version" for="{uid}-version" class="min-w-[16rem] flex-1">
    <PickSelect
      id="{uid}-version"
      class="h-8 w-full text-sm"
      label="Version"
      value={selectedId}
      options={entries.map(([id, p]) => ({ value: id, label: `${p.label}${p.locked ? ' 🔒' : ''}` }))}
      onchange={(v) => (selectedId = v)}
    />
  </Field>
  <div class="flex flex-wrap gap-2 pb-1">
    <Button variant="outline" size="sm" onclick={onCreate}>+ New</Button>
    <Button variant="outline" size="sm" onclick={onDuplicate}>Duplicate</Button>
    <Button
      variant="outline"
      size="sm"
      disabled={selected.locked}
      title={selected.locked ? 'The built-in default cannot be deleted.' : 'Delete this version.'}
      onclick={onDelete}
    >
      Delete
    </Button>
  </div>
</div>
