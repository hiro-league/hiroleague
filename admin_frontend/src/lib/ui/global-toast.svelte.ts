/**
 * Shell-level toast for errors that escape feature controllers (e.g. unhandled
 * promise rejections registered in hooks.client.ts).
 */
import { createToastNotifier } from './create-toast-notifier.svelte';

export const globalToast = createToastNotifier();
