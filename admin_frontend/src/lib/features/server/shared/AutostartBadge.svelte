<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';

  let { method }: { method: string | null } = $props();
</script>

<Badge variant={method && method !== 'skipped' ? 'secondary' : 'outline'}>
  {method ?? '-'}
</Badge>
