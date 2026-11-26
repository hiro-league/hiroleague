<script lang="ts">
  // Installing or removing an app the core installs needs one administrator step, so the page gives the command to
  // run instead of a button that would need one (Installing apps).
  import { Check, Copy } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import SectionLabel from '$kit/ui/section-label.svelte';
  import type { Installs } from '../state/installs.svelte';

  let { inst }: { inst: Installs } = $props();
</script>

<Dialog.Root
  open={inst.command !== null}
  onOpenChange={(next) => {
    if (!next) inst.closeCommand();
  }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>{inst.command?.title}</Dialog.Title>
    </Dialog.Header>
    {#if inst.command}
      <div class="grid gap-3">
        {#if inst.command.lines.length}
          <SectionLabel>In an administrator terminal</SectionLabel>
        {/if}
        {#each inst.command.lines as line (line)}
          <div class="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
            <code class="min-w-0 flex-1 font-mono text-xs break-all">{line}</code>
            <Button size="icon" variant="ghost" title="Copy" aria-label="Copy the command" onclick={() => void inst.copy(line)}>
              {#if inst.copied === line}<Check class="text-success" size={14} />{:else}<Copy size={14} />{/if}
            </Button>
          </div>
        {/each}
        {#if inst.command.note}<p class="font-sans text-sm text-muted-foreground">{inst.command.note}</p>{/if}
      </div>
    {/if}
    <Dialog.Footer>
      <Button onclick={() => inst.closeCommand()}>Done</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
