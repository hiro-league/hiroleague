<script lang="ts">
  import { FileWarning } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import { stderrTitle } from './server-format';

  let {
    exists,
    recent,
    mtime,
    size,
    onclick
  }: {
    exists: boolean;
    recent: boolean;
    mtime: string | null;
    size: number;
    onclick: () => void;
  } = $props();
</script>

{#if exists}
  <Button
    size="sm"
    variant={recent ? 'destructive' : 'outline'}
    title={stderrTitle(mtime, size)}
    {onclick}
  >
    <FileWarning size={13} /> stderr
  </Button>
{/if}
