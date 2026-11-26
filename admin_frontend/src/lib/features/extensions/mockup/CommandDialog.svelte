<script lang="ts">
  // mockup (Installing apps, phase 5, task 6): installing or removing an app the core installs needs one
  // administrator step, so the page gives the command to run instead of a button that would need one.
  import { Check, Copy } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import MockupBadge from '$kit/ui/mockup-badge.svelte';
  import SectionLabel from '$kit/ui/section-label.svelte';
  import type { InstallsMock } from './installs-mock.svelte';

  let { mock }: { mock: InstallsMock } = $props();
</script>

<Dialog.Root
  open={mock.command !== null}
  onOpenChange={(next) => {
    if (!next) mock.closeCommand();
  }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2">{mock.command?.title} <MockupBadge /></Dialog.Title>
    </Dialog.Header>
    {#if mock.command}
      <div class="grid gap-3">
        <SectionLabel>In an administrator terminal</SectionLabel>
        {#each mock.command.lines as line (line)}
          <div class="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
            <code class="min-w-0 flex-1 font-mono text-xs break-all">{line}</code>
            <Button size="icon" variant="ghost" title="Copy" aria-label="Copy the command" onclick={() => void mock.copy(line)}>
              {#if mock.copied}<Check class="text-success" size={14} />{:else}<Copy size={14} />{/if}
            </Button>
          </div>
        {/each}
      </div>
    {/if}
    <Dialog.Footer>
      <Button onclick={() => mock.closeCommand()}>Done</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
