<script lang="ts">
  /**
   * /sign-in (Phase 8): where an app's site sends people to sign in (?for=<app>&next=<path>). The layout
   * shows the sign-in page to someone signed out; someone already signed in lands here and goes straight
   * back to the app (the backend adds a one-time code), or to the dashboard when no app asked.
   */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import { page } from '$app/state';
  import { backToAppUrl } from '$lib/api/auth';
  import Loading from '$kit/ui/loading.svelte';

  const forApp = page.url.searchParams.get('for');

  onMount(() => {
    if (forApp) {
      window.location.replace(backToAppUrl(forApp, page.url.searchParams.get('next')));
    } else {
      void goto(`${base}/`, { replaceState: true });
    }
  });
</script>

<div class="grid min-h-[50vh] place-items-center">
  <Loading label={forApp ? 'Taking you back…' : 'Signed in'} />
</div>
