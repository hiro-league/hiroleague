<script lang="ts">
  // HiroLeague's mark, where the shared shell shows an app's icon (the menu's head, the sign-in page).
  import { base } from '$app/paths';

  let { class: className = 'size-4' }: { class?: string } = $props();
</script>

<img src={`${base}/images/logo-only2.png`} alt="" class={['object-contain', className]} aria-hidden="true" />
