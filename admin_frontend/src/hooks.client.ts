import type { HandleClientError } from '@sveltejs/kit';
import { friendlyErrorMessage } from '$lib/errors/friendly-message';
import { serverReadiness } from '$lib/runtime/server-readiness.svelte';
import { globalToast } from '$lib/ui/global-toast.svelte';

export const handleError: HandleClientError = ({ error }) => {
  console.error(error);
  return { message: friendlyErrorMessage(error) };
};

window.addEventListener('unhandledrejection', (event) => {
  console.error(event.reason);
  if (!serverReadiness.ready) return;
  globalToast.notify('error', friendlyErrorMessage(event.reason));
});
