<script lang="ts">
  import { Badge } from '$kit/components/ui/badge/index.js';

  let { method }: { method: string | null } = $props();
</script>

<Badge variant={method && method !== 'skipped' ? 'secondary' : 'outline'}>
  {method ?? '-'}
</Badge>
