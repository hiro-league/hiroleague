<script lang="ts">
  import { cn } from '$lib/utils';

  type Props = {
    text: string;
    class?: string;
  };

  let { text, class: className }: Props = $props();
</script>

<p class={cn('text-muted-foreground', className)}>{text}</p>
