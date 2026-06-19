<script lang="ts">
  import { ChevronsDownUp, ChevronsUpDown } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';

  let {
    onExpand,
    onCollapse,
    disabled = false
  }: {
    onExpand: () => void;
    onCollapse: () => void;
    disabled?: boolean;
  } = $props();
</script>

<Button
  variant="outline"
  size="sm"
  title="Expand all sections"
  aria-label="Expand all sections"
  {disabled}
  onclick={onExpand}
>
  <ChevronsUpDown size={14} aria-hidden="true" />
</Button>
<Button
  variant="outline"
  size="sm"
  title="Collapse all sections"
  aria-label="Collapse all sections"
  {disabled}
  onclick={onCollapse}
>
  <ChevronsDownUp size={14} aria-hidden="true" />
</Button>
