<script lang="ts">
  import { Check, Copy } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';

  let {
    value,
    copied,
    oncopy
  }: {
    value: string;
    copied: boolean;
    oncopy: () => void;
  } = $props();
</script>

<span class="font-sans text-sm font-medium text-muted-foreground">Workspace public key (Ed25519, base64)</span>
<div class="flex gap-2">
  <input class="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 font-mono text-sm" readonly {value} />
  <Button
    class="size-9"
    variant="outline"
    size="icon"
    onclick={oncopy}
    aria-label="Copy public key"
    title="Copy to clipboard"
  >
    {#if copied}
      <Check class="text-emerald-500" size={16} />
    {:else}
      <Copy size={16} />
    {/if}
  </Button>
</div>
