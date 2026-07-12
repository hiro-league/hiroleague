<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { FieldSpec } from '../../shared/schema-form';

  // `draft` is the controller's reactive $state proxy; fields bind into it by key.
  // Typed loosely because a schema field can be a string, boolean, or list-as-string.
  let {
    fields,
    draft,
    secretSet,
    onClearSecret
  }: {
    fields: FieldSpec[];
    draft: Record<string, any>;
    secretSet: Record<string, boolean>;
    onClearSecret: (key: string) => void;
  } = $props();
</script>

<div class="flex flex-col gap-4">
  {#each fields as field (field.key)}
    {#if field.type === 'boolean'}
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={draft[field.key]} />
        <span>{field.title}</span>
      </label>
      {#if field.description}
        <p class="-mt-3 text-xs text-muted-foreground">{field.description}</p>
      {/if}
    {:else if field.type === 'enum'}
      <FormField label={field.title} hint={field.description}>
        <select bind:value={draft[field.key]}>
          {#each field.enumValues ?? [] as option (option)}
            <option value={option}>{option}</option>
          {/each}
        </select>
      </FormField>
    {:else if field.secret}
      <FormField
        label={field.title}
        hint={secretSet[field.key]
          ? `${field.description} (stored — leave blank to keep the current value)`
          : field.description}
      >
        <input
          type="password"
          autocomplete="off"
          bind:value={draft[field.key]}
          placeholder={secretSet[field.key] ? '•••••••• set' : 'not set'}
        />
      </FormField>
      {#if secretSet[field.key]}
        <div class="-mt-2">
          <Button variant="outline" size="sm" onclick={() => onClearSecret(field.key)}>Clear</Button>
        </div>
      {/if}
    {:else}
      <FormField
        label={field.title}
        hint={field.type === 'array' ? `${field.description} (comma-separated)` : field.description}
      >
        <input
          type={field.type === 'integer' || field.type === 'number' ? 'number' : 'text'}
          bind:value={draft[field.key]}
        />
      </FormField>
    {/if}
  {/each}
</div>
