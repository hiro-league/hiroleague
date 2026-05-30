<script lang="ts">
  import { base } from '$app/paths';
  import { KeyRound } from '@lucide/svelte';
  import AdminPageLinkAction from '$lib/components/page/AdminPageLinkAction.svelte';

  type Props = {
    busy?: boolean;
  };

  let { busy = false }: Props = $props();
</script>

<AdminPageLinkAction
  href={`${base}/catalog/?tab=active-providers`}
  icon={KeyRound}
  variant="outline"
  size="sm"
  class={busy ? 'pointer-events-none opacity-60' : ''}
>
  Active providers
</AdminPageLinkAction>
