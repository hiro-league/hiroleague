<script lang="ts">
  import { base } from '$app/paths';
  import { ArrowUpRight, Database } from '@lucide/svelte';
  import AdminPageLinkAction from '$lib/components/page/AdminPageLinkAction.svelte';
  import { KNOWLEDGE_BROWSE_HREF } from '$lib/features/knowledge/shared/knowledge-pure';

  type Props = {
    busy?: boolean;
  };

  let { busy = false }: Props = $props();
</script>

<AdminPageLinkAction
  href={`${base}${KNOWLEDGE_BROWSE_HREF}`}
  icon={Database}
  variant="outline"
  size="sm"
  class={busy ? 'pointer-events-none opacity-60' : ''}
  title="Open Knowledge — Browse tab"
>
  Browse Knowledge
  <ArrowUpRight size={14} strokeWidth={2.25} aria-hidden="true" />
</AdminPageLinkAction>
